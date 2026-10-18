"""Egress policy shared by the API (pre-validation of researcher-entered URLs) and the controlled fetch service."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

ALLOWED_PORTS = {80, 443}
ALLOWED_TYPES = {"text/html", "application/xhtml+xml", "application/pdf", "text/plain", "application/zip",
                 "application/x-zip-compressed", "application/xml", "text/xml", "application/octet-stream",
                 "application/json", "application/atom+xml", "application/rss+xml"}
METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data", "metadata.azure.internal"}
CGNAT = ipaddress.ip_network("100.64.0.0/10")


class FetchBlocked(Exception):
    """The request violates the egress policy. Never retried."""

    def __init__(self, reason: str, url: str):
        super().__init__(f"{reason}: {url}")
        self.reason = reason
        self.url = url


def ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip_is_public(ip.ipv4_mapped)
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
            or ip.is_unspecified or not ip.is_global):
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in CGNAT:
        return False
    return True


def validate_url(url: str) -> tuple[str, str, int]:
    """Return (normalized_url, hostname, port) or raise FetchBlocked."""
    if len(url) > 2048:
        raise FetchBlocked("url_too_long", url[:100])
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise FetchBlocked("malformed_url", url) from exc
    if parts.scheme not in ("http", "https"):
        raise FetchBlocked("scheme_not_allowed", url)
    if parts.username or parts.password:
        raise FetchBlocked("credentials_in_url", url)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise FetchBlocked("missing_host", url)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise FetchBlocked("invalid_port", url) from exc
    if port not in ALLOWED_PORTS:
        raise FetchBlocked("port_not_allowed", url)
    if host in METADATA_HOSTS or host == "localhost" or host.endswith(".localhost") or host.endswith(".internal") \
            or host.endswith(".local"):
        raise FetchBlocked("host_not_allowed", url)
    literal = None
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        # Reject numeric hosts that are not canonical dotted-quad/IPv6 (e.g. 2130706433, 0x7f.1, 127.1).
        if all(p.isdigit() or p.lower().startswith("0x") for p in host.split(".")):
            raise FetchBlocked("non_canonical_ip", url) from None
    if literal is not None and not ip_is_public(literal):
        raise FetchBlocked("private_address", url)
    normalized = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))
    return normalized, host, port


