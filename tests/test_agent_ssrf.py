"""SSRF guard for web_fetch: the tool fetches model-chosen URLs, so it must
refuse internal targets (cloud metadata, localhost, private ranges) and any
public URL that redirects inward."""

from __future__ import annotations

import socket

import pytest

from essarion_build.agent import _ssrf
from essarion_build.agent._ssrf import UnsafeUrlError, assert_public_url
from essarion_build.agent._tools import bind_tools, web_fetch


def test_ip_classification():
    for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "172.16.0.1",
               "169.254.169.254", "0.0.0.0", "::1", "fe80::1",
               "::ffff:127.0.0.1"):
        assert _ssrf._ip_is_public(ip) is False, ip
    for ip in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"):
        assert _ssrf._ip_is_public(ip) is True, ip


def test_non_http_scheme_rejected():
    with pytest.raises(UnsafeUrlError):
        assert_public_url("file:///etc/passwd")
    with pytest.raises(UnsafeUrlError):
        assert_public_url("gopher://x/")


def test_assert_blocks_private_resolution(monkeypatch):
    monkeypatch.setattr(
        _ssrf.socket, "getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(UnsafeUrlError, match="non-public"):
        assert_public_url("http://metadata.evil.test/")


def test_assert_allows_public_resolution(monkeypatch):
    monkeypatch.setattr(
        _ssrf.socket, "getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert_public_url("https://example.test/")  # must not raise


def test_web_fetch_refuses_internal_targets(tmp_path):
    bind_tools(tmp_path)
    for url in ("http://169.254.169.254/latest/meta-data/",
                "http://127.0.0.1:8000/admin",
                "http://10.1.2.3/"):
        out = web_fetch(url)
        assert out.startswith("(refused to fetch"), out


def test_web_fetch_blocks_public_to_internal_redirect(tmp_path, monkeypatch):
    """A host that passes the initial check but 302s to an internal address
    must still be refused — the redirect handler re-validates each hop."""
    bind_tools(tmp_path)

    # Initial host resolves public; the redirect handler will be handed an
    # internal URL and must raise.
    monkeypatch.setattr(
        _ssrf.socket, "getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", (
            "127.0.0.1" if host == "internal.test" else "93.184.216.34", 0))],
    )
    handler = _ssrf._ValidatingRedirectHandler()
    with pytest.raises(UnsafeUrlError):
        handler.redirect_request(
            req=None, fp=None, code=302, msg="", headers={},
            newurl="http://internal.test/secrets",
        )
