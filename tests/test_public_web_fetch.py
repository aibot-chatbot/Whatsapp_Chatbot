"""Exercise the real httpx/httpcore path with mocked DNS and TCP streams."""

from unittest.mock import patch

import pytest

from app.services import public_web_fetch_service as fetcher


class HTTPStream:
    def __init__(self, body=b"<html>public page</html>", status="200 OK", headers=""):
        self.response = (
            f"HTTP/1.1 {status}\r\nContent-Length: {len(body)}\r\n{headers}\r\n".encode()
            + body
        )
        self.sent = b""
        self.tls_hostname = None

    def read(self, max_bytes, timeout=None):
        result, self.response = self.response[:max_bytes], self.response[max_bytes:]
        return result

    def write(self, buffer, timeout=None):
        self.sent += buffer

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls_hostname = server_hostname
        assert ssl_context.check_hostname
        return self

    def get_extra_info(self, name):
        return None

    def close(self):
        pass


def dns(address):
    return [(2, 1, 6, "", (address, 443))]


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/",
    "http://100.100.100.200/", "http://168.63.129.16/", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::a00:1]/",
    "http://224.0.0.1/", "http://[2002:a00:1::]/",
    "ftp://example.org/", "https://user:password@example.org/",
])
def test_unsafe_literal_or_protocol_never_opens_connection(url):
    with patch("httpcore._backends.sync.SyncBackend.connect_tcp") as connect:
        with pytest.raises(ValueError):
            fetcher.fetch_public_html(url)
    connect.assert_not_called()


@pytest.mark.parametrize("answers", [dns("127.0.0.1"), dns("8.8.8.8") + dns("10.0.0.1")])
def test_hostname_with_private_dns_answer_never_opens_connection(answers):
    with (
        patch.object(fetcher.socket, "getaddrinfo", return_value=answers),
        patch("httpcore._backends.sync.SyncBackend.connect_tcp") as connect,
    ):
        with pytest.raises(ValueError):
            fetcher.fetch_public_html("https://attacker.example/")
    connect.assert_not_called()


def test_validated_ip_is_pinned_while_host_and_tls_identity_are_preserved():
    stream = HTTPStream()
    with (
        patch.object(fetcher.socket, "getaddrinfo", side_effect=[dns("8.8.8.8"), dns("127.0.0.1")]) as resolve,
        patch("httpcore._backends.sync.SyncBackend.connect_tcp", return_value=stream) as connect,
        patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:9876"}),
    ):
        html, final_url = fetcher.fetch_public_html("https://example.org/page")

    assert html == "<html>public page</html>"
    assert final_url == "https://example.org/page"
    assert resolve.call_count == 1  # No second attacker-controlled DNS resolution.
    assert connect.call_args.kwargs["host"] == "8.8.8.8"
    assert stream.tls_hostname == "example.org"
    assert b"Host: example.org\r\n" in stream.sent


@pytest.mark.parametrize("location", ["http://169.254.169.254/latest/meta-data/", "https://attacker.example/private"])
def test_redirect_target_is_revalidated_before_connecting(location):
    stream = HTTPStream(status="302 Found", headers=f"Location: {location}\r\n")
    with (
        patch.object(fetcher.socket, "getaddrinfo", side_effect=[dns("8.8.8.8"), dns("127.0.0.1")]),
        patch("httpcore._backends.sync.SyncBackend.connect_tcp", return_value=stream) as connect,
    ):
        with pytest.raises(ValueError):
            fetcher.fetch_public_html("https://attacker.example/")
    assert connect.call_count == 1


def test_public_relative_redirect_preserves_final_url():
    streams = [HTTPStream(status="302 Found", headers="Location: /docs/\r\n"), HTTPStream()]
    with (
        patch.object(fetcher.socket, "getaddrinfo", return_value=dns("8.8.8.8")),
        patch("httpcore._backends.sync.SyncBackend.connect_tcp", side_effect=streams),
    ):
        _, final_url = fetcher.fetch_public_html("https://example.org/")
    assert final_url == "https://example.org/docs/"


def test_response_size_is_bounded():
    with (
        patch.object(fetcher, "MAX_HTML_BYTES", 16),
        patch("httpcore._backends.sync.SyncBackend.connect_tcp", return_value=HTTPStream(b"a" * 17)),
    ):
        with pytest.raises(ValueError, match="limit"):
            fetcher.fetch_public_html("http://8.8.8.8/")


def test_redirect_loop_is_bounded():
    with patch(
        "httpcore._backends.sync.SyncBackend.connect_tcp",
        side_effect=lambda **kwargs: HTTPStream(status="302 Found", headers="Location: /again\r\n"),
    ) as connect:
        with pytest.raises(ValueError, match="redirect limit"):
            fetcher.fetch_public_html("http://8.8.8.8/")
    assert connect.call_count == fetcher.MAX_REDIRECTS + 1


def test_unrequested_compression_is_rejected_before_decompression():
    with patch(
        "httpcore._backends.sync.SyncBackend.connect_tcp",
        return_value=HTTPStream(b"not-valid-gzip", headers="Content-Encoding: gzip\r\n"),
    ):
        with pytest.raises(ValueError, match="uncompressed"):
            fetcher.fetch_public_html("http://8.8.8.8/")


def test_discovery_uses_redirected_page_as_relative_link_base():
    from app.services import knowledge_service

    with patch.object(knowledge_service, "fetch_public_html", return_value=(
        '<a href="about">About</a><a href="ftp://www.example.org/file">FTP</a>',
        "https://www.example.org/docs/",
    )):
        links = knowledge_service.discover_website_links("http://example.org/")
    assert links == ["https://www.example.org/docs", "https://www.example.org/docs/about"]


def test_extraction_uses_shared_public_fetcher():
    from app.services import knowledge_service

    with (
        patch.object(knowledge_service, "fetch_public_html", side_effect=ValueError("private destination")) as fetch,
        patch.object(knowledge_service.trafilatura, "extract") as extract,
    ):
        with pytest.raises(ValueError, match="private destination"):
            knowledge_service.fetch_and_parse_url("http://127.0.0.1/")
    fetch.assert_called_once()
    extract.assert_not_called()


def test_public_html_still_extracts_business_content():
    from app.services import knowledge_service

    content = "Our company provides installation and maintenance services for local businesses. " * 4
    with patch.object(knowledge_service, "fetch_public_html", return_value=(
        f"<html><body><article><h1>Our services</h1><p>{content}</p></article></body></html>",
        "https://example.org/",
    )):
        result = knowledge_service.fetch_and_parse_url("https://example.org/")
    assert "installation and maintenance" in result
