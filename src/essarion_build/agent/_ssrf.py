"""SSRF guard for the agent's `web_fetch` tool.

`web_fetch` retrieves URLs the *model* chooses, and the model's choice can be
steered by untrusted content it just read (a malicious repo file, a page it
fetched). Without a guard that's a server-side request forgery primitive: a
fetch aimed at the cloud metadata endpoint
(`http://169.254.169.254/latest/meta-data/…`), a `localhost` service, or an
RFC-1918 host. In the cloud product each session is a container, so an
internal fetch can reach the container's metadata/sidecars.

This refuses any URL whose host resolves to a non-public address, and — via a
redirect handler that re-checks every hop — refuses a public URL that
redirects inward. Standard library only (the package is zero-dependency).
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeUrlError(ValueError):
    """The URL's scheme is disallowed or its host resolves to a non-public
    (private / loopback / link-local / reserved) address."""


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return _ip_is_public(str(addr.ipv4_mapped))
    return True


def assert_public_url(url: str) -> None:
    """Raise :class:`UnsafeUrlError` unless `url` is an http(s) URL whose host
    resolves only to public addresses (every A/AAAA record is checked)."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme {parsed.scheme!r} is not allowed (http/https only)")
    host = parsed.hostname
    if not host:
        raise UnsafeUrlError(f"URL {url!r} has no host")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host {host!r}: {exc}") from None
    if not infos:
        raise UnsafeUrlError(f"host {host!r} did not resolve")
    for info in infos:
        ip = info[4][0]
        if not _ip_is_public(ip):
            raise UnsafeUrlError(
                f"host {host!r} resolves to non-public address {ip} — refusing to fetch"
            )


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs the SSRF check on every redirect target before following it, so
    a public→internal redirect can't slip past the initial validation."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_safe_opener() -> urllib.request.OpenerDirector:
    """An opener whose redirect handling is SSRF-validated."""
    return urllib.request.build_opener(_ValidatingRedirectHandler())


__all__ = ["UnsafeUrlError", "assert_public_url", "build_safe_opener"]
