"""The visitor IP must come from CF-Connecting-IP only when Cloudflare really sent the request.

Behind Cloudflare the chain is visitor -> Cloudflare edge -> Fly proxy -> app. Fly appends the
address that connected to it, so ProxyFix (x_for=1) yields the Cloudflare edge. Anyone calling
the Fly origin directly can send a CF-Connecting-IP header, so it is trusted only from
Cloudflare's published ranges. All addresses here are documentation ranges.
"""
import os
from unittest import mock

import pytest
from flask import request


@pytest.fixture
def client():
    env = {
        "FLASK_ENV": "testing", "RATELIMIT_ENABLED": "false", "TRUSTED_PROXY_HOPS": "1",
        "SECRET_KEY": "test-secret-key-for-cloudflare-ip-tests",
    }
    with mock.patch.dict(os.environ, env):
        from app import create_app
        app = create_app()
    app.add_url_rule("/__client_ip", "client_ip_probe", lambda: request.remote_addr or "")
    return app.test_client()


def _ip(client, *, forwarded, cf_ip=None):
    headers = {"X-Forwarded-For": forwarded}
    if cf_ip is not None:
        headers["CF-Connecting-IP"] = cf_ip
    return client.get("/__client_ip", headers=headers,
                      environ_base={"REMOTE_ADDR": "172.16.0.1"}).get_data(as_text=True)


def test_proxied_request_uses_the_visitor_ip_cloudflare_reports(client):
    assert _ip(client, forwarded="203.0.113.7, 162.158.1.2", cf_ip="203.0.113.7") == "203.0.113.7"


def test_ipv6_cloudflare_edge_is_trusted_too(client):
    assert _ip(client, forwarded="2001:db8::5, 2606:4700::1", cf_ip="2001:db8::5") == "2001:db8::5"


def test_direct_caller_cannot_spoof_its_ip_with_the_header(client):
    # The attacker skips Cloudflare and calls Fly directly; Fly appends the attacker's real address.
    assert _ip(client, forwarded="198.51.100.9", cf_ip="203.0.113.250") == "198.51.100.9"


def test_dns_only_traffic_keeps_todays_behaviour(client):
    assert _ip(client, forwarded="198.51.100.9") == "198.51.100.9"


@pytest.mark.parametrize("bad", ["not-an-ip", "", "203.0.113.7, 198.51.100.1", "999.1.1.1"])
def test_malformed_header_from_cloudflare_keeps_the_edge_address(client, bad):
    assert _ip(client, forwarded="203.0.113.7, 162.158.1.2", cf_ip=bad) == "162.158.1.2"
