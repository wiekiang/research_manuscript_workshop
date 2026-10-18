"""Controlled fetch service (PRODUCT_SPEC §4, §8 external-access boundary 1).

The only component allowed to reach previously unknown public URLs. For every hop it:
  * accepts only http/https on ports 80/443, rejects credentials in URLs and non-canonical IP encodings;
  * resolves DNS once and rejects the request if ANY resolved address is private, loopback, link-local,
    multicast, reserved, CGNAT, unspecified or a cloud metadata address;
  * pins the connection to the vetted IP (Host header + TLS SNI/verification on the original hostname), so a DNS
    change between check and connect (rebinding) cannot redirect it;
  * follows redirects manually, re-validating each location;
  * caps size, time and content type; honours robots.txt for automated (non-researcher-initiated) fetches.
Responses are returned as quarantined bytes; the caller scans them and commits a source artifact before any
research worker or agent may read them.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
import urllib.robotparser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from rp_contracts.netpolicy import ALLOWED_TYPES, FetchBlocked, ip_is_public, validate_url

from ..config import get_worker_settings


class FetchFailed(Exception):
    def __init__(self, reason: str, url: str, retryable: bool, status: int | None = None, retry_after: int | None = None):
        super().__init__(f"{reason}: {url}")
        self.reason = reason
        self.url = url
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after


@dataclass
class Hop:
    url: str
    ip: str
    status: int


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status: int
    content: bytes
    media_type: str
    headers: dict[str, str]
    hops: list[Hop]
    retrieved_at: datetime
    not_modified: bool = False
    robots: str = "not_checked"
    truncated: bool = False
    notes: list[str] = field(default_factory=list)


Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


class HostRateLimiter:
    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self._last.get(host, 0) + self.min_interval - now
            self._last[host] = max(now, self._last.get(host, 0) + self.min_interval)
        if delay > 0:
            await asyncio.sleep(delay)


_rate = HostRateLimiter()


class ControlledFetcher:
    def __init__(self, resolver: Resolver | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 max_bytes: int | None = None, allow_private: bool | None = None):
        s = get_worker_settings()
        self.resolver = resolver or system_resolver
        self.transport = transport
        self.max_bytes = max_bytes or s.fetch_max_bytes
        self.timeout = s.fetch_timeout_seconds
        self.max_redirects = s.fetch_max_redirects
        self.user_agent = s.fetch_user_agent
        self.allow_private = s.fetch_allow_private_for_tests if allow_private is None else allow_private
        if self.allow_private and s.environment not in ("test", "local"):
            raise RuntimeError("private-address fetching may only be enabled in isolated tests")

    async def _vet(self, url: str) -> tuple[str, str, str, int]:
        normalized, host, port = validate_url(url)
        try:
            ipaddress.ip_address(host)
            addrs = [host]
        except ValueError:
            try:
                addrs = await self.resolver(host, port)
            except OSError as exc:
                raise FetchFailed("dns_failure", url, retryable=True) from exc
        if not addrs:
            raise FetchFailed("dns_no_address", url, retryable=True)
        for a in addrs:
            if not self.allow_private and not ip_is_public(ipaddress.ip_address(a)):
                raise FetchBlocked("private_address", url)
        return normalized, host, addrs[0], port

    async def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            res = await self.fetch(robots_url, check_robots=False, accept_types={"text/plain", "text/html",
                                                                                   "application/octet-stream"},
                                   max_bytes=512 * 1024)
        except (FetchFailed, FetchBlocked):
            return True  # unreachable robots.txt does not forbid; the failure is recorded by the caller
        if res.status >= 400:
            return True
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(res.content.decode("utf-8", "replace").splitlines())
        return rp.can_fetch(self.user_agent, url)

    async def fetch(self, url: str, *, check_robots: bool = False, etag: str | None = None,
                    last_modified: str | None = None, accept_types: set[str] | None = None,
                    max_bytes: int | None = None) -> FetchResult:
        accept = accept_types or ALLOWED_TYPES
        limit = max_bytes or self.max_bytes
        robots = "not_checked"
        if check_robots:
            if not await self.robots_allows(url):
                raise FetchBlocked("robots_disallowed", url)
            robots = "allowed"
        hops: list[Hop] = []
        current = url
        for _ in range(self.max_redirects + 1):
            normalized, host, ip, port = await self._vet(current)
            parts = urlsplit(normalized)
            ip_host = f"[{ip}]" if ":" in ip else ip
            netloc = ip_host if port in (80, 443) and ((parts.scheme == "https") == (port == 443)) else f"{ip_host}:{port}"
            pinned = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
            headers = {"Host": parts.netloc, "User-Agent": self.user_agent, "Accept": ", ".join(sorted(accept))}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            await _rate.wait(host)
            async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout, follow_redirects=False,
                                         trust_env=False) as client:
                try:
                    req = client.build_request("GET", pinned, headers=headers,
                                               extensions={"sni_hostname": host} if parts.scheme == "https" else {})
                    resp = await client.send(req, stream=True)
                except httpx.TimeoutException as exc:
                    raise FetchFailed("timeout", current, retryable=True) from exc
                except httpx.HTTPError as exc:
                    raise FetchFailed("connection_error", current, retryable=True) from exc
                try:
                    hops.append(Hop(normalized, ip, resp.status_code))
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchFailed("redirect_without_location", current, retryable=False)
                        current = urljoin(normalized, loc)
                        continue
                    if resp.status_code == 304:
                        return FetchResult(url, normalized, 304, b"", "", dict(resp.headers), hops,
                                           datetime.now(UTC), not_modified=True, robots=robots)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        ra = resp.headers.get("retry-after")
                        raise FetchFailed("upstream_unavailable", current, retryable=True, status=resp.status_code,
                                          retry_after=int(ra) if ra and ra.isdigit() else None)
                    if resp.status_code >= 400:
                        raise FetchFailed("http_error", current, retryable=False, status=resp.status_code)
                    media = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
                    if media not in accept:
                        raise FetchBlocked("content_type_not_allowed", current)
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > limit:
                        raise FetchBlocked("too_large", current)
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > limit:
                            raise FetchBlocked("too_large", current)
                    return FetchResult(url, normalized, resp.status_code, bytes(buf), media,
                                       {k.lower(): v for k, v in resp.headers.items()}, hops, datetime.now(UTC),
                                       robots=robots)
                finally:
                    await resp.aclose()
        raise FetchBlocked("too_many_redirects", url)
