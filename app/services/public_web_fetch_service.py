"""Bounded public-page fetching for user-selected knowledge URLs."""

import ipaddress
import socket
from urllib.parse import urljoin

import httpx


MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
_NAT64_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("64:ff9b:1::/48"),
)


def _public_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if str(address) == "168.63.129.16":  # Azure platform virtual service address.
        return False
    if address.version == 6:
        if address.sixtofour or address.teredo or any(address in net for net in _NAT64_NETWORKS):
            return False
        if address.ipv4_mapped:
            return _public_address(str(address.ipv4_mapped))
    return True


def _resolve_public_url(value):
    url = httpx.URL(value)
    if url.scheme not in {"http", "https"} or not url.host or url.userinfo:
        raise ValueError("A public HTTP or HTTPS URL without credentials is required.")
    host = url.raw_host.decode("ascii")
    if "%" in host:
        raise ValueError("Scoped network addresses are not supported.")
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        addresses = [
            row[4][0]
            for row in socket.getaddrinfo(
                host, url.port or (443 if url.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        ]
    if not addresses or not all(_public_address(address) for address in addresses):
        raise ValueError("Only publicly routable website addresses are allowed.")
    return url, addresses[0]


def fetch_public_html(url):
    """Return HTML and final URL; every connection uses a validated IP literal.

    Pinning the destination avoids a second hostname resolution at connect time.
    Host and TLS SNI remain the original hostname, with certificate checks enabled.
    """
    for hop in range(MAX_REDIRECTS + 1):
        target, address = _resolve_public_url(url)
        # A fresh client per hop prevents cookies or a pooled TLS connection from
        # crossing virtual hosts that happen to share the same public IP.
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=15.0) as client:
            with client.stream(
                "GET", target.copy_with(host=address),
                headers={
                    "Host": target.netloc.decode("ascii"),
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Encoding": "identity",
                },
                extensions={"sni_hostname": target.raw_host.decode("ascii")},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or hop == MAX_REDIRECTS:
                        raise ValueError("Website redirect limit reached or target missing.")
                    url = urljoin(str(target), location)
                    continue
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ValueError("Website ignored the uncompressed response requirement.")
                content = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    content.extend(chunk)
                    if len(content) > MAX_HTML_BYTES:
                        raise ValueError("Website response exceeds the 5 MB limit.")
                html = httpx.Response(
                    response.status_code, headers=response.headers, content=bytes(content)
                ).text
                return html, str(target)
