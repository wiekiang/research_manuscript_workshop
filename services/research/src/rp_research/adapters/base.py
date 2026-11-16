"""Capability-based scholarly provider contract (PRODUCT_SPEC §2.5).

Each adapter advertises which operations it supports; unsupported operations raise `Unsupported` instead of
being simulated (e.g. Crossref metadata is never presented as full text). HTTP errors are classified so the
workflow can back off (429/5xx), stop the adapter (401/402/403) or continue with other providers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import httpx

from rp_contracts.literature import Capability, PaperRecord

USER_AGENT = "ResearchPlatform/1.0 (scholarly-adapter)"


class ProviderError(Exception):
    def __init__(self, provider: str, kind: str, message: str, status: int | None = None, retry_after: int | None = None):
        super().__init__(f"{provider}: {kind}: {message}")
        self.provider = provider
        self.kind = kind  # rate_limited | unavailable | access_denied | payment_required | not_found | http_error | bad_response
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate_limited", "unavailable")


class Unsupported(ProviderError):
    def __init__(self, provider: str, capability: Capability):
        super().__init__(provider, "unsupported", f"capability {capability.value} is not supported")


class Disabled(ProviderError):
    def __init__(self, provider: str, reason: str):
        super().__init__(provider, "disabled", reason)


@dataclass
class SearchPage:
    records: list[PaperRecord]
    total: int | None
    next_cursor: str | None = None
    partial: bool = False
    notes: list[str] = field(default_factory=list)
    raw: dict | None = None


@dataclass
class Quota:
    remaining: int | None
    limit: int | None
    reset_at: str | None = None


_transport: httpx.AsyncBaseTransport | None = None

MAX_ATTEMPTS = 3
MAX_RETRY_WAIT = 30  # longer Retry-After values are surfaced as rate_limited for the workflow to back off
_sleep = asyncio.sleep  # patched in tests


def use_transport(t: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject recorded fixtures through an httpx transport."""
    global _transport
    _transport = t


class Adapter:
    name = "base"
    capabilities: dict[Capability, bool] = {}
    _stopped: ProviderError | None = None  # set after 401/402/403; later calls fail fast without contacting the provider

    def supports(self, cap: Capability) -> bool:
        return self.capabilities.get(cap, False)

    def _require(self, cap: Capability) -> None:
        if not self.supports(cap):
            raise Unsupported(self.name, cap)

    async def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        """GET with the documented failure policy: retry 429/5xx/timeouts (honouring Retry-After up to a cap), stop
        the adapter after 401/402/403, and report any other non-2xx status as a provider error so callers fall back."""
        if self._stopped is not None:
            raise self._stopped
        async with httpx.AsyncClient(transport=_transport, timeout=30.0, headers={"User-Agent": USER_AGENT,
                                                                                **(headers or {})}) as c:
            for attempt in range(MAX_ATTEMPTS):
                last = attempt == MAX_ATTEMPTS - 1
                try:
                    r = await c.get(url, params=params)
                except httpx.TimeoutException as exc:
                    if last:
                        raise ProviderError(self.name, "unavailable", "timeout") from exc
                    await _sleep(1 + attempt)
                    continue
                except httpx.HTTPError as exc:
                    raise ProviderError(self.name, "unavailable", str(exc)) from exc
                code = r.status_code
                if 200 <= code < 300:
                    return r
                if code in (401, 402, 403):
                    kind = "payment_required" if code == 402 else "access_denied"
                    self._stopped = ProviderError(self.name, kind, f"HTTP {code}; adapter stopped", code)
                    raise self._stopped
                if code == 429:
                    ra = r.headers.get("retry-after", "")
                    wait = int(ra) if ra.isdigit() else 30
                    if last or wait > MAX_RETRY_WAIT:
                        raise ProviderError(self.name, "rate_limited", "rate limited", 429, wait)
                    await _sleep(wait)
                    continue
                if code >= 500:
                    if last:
                        raise ProviderError(self.name, "unavailable", f"HTTP {code}", code)
                    await _sleep(1 + attempt)
                    continue
                if code == 404:
                    raise ProviderError(self.name, "not_found", "not found", 404)
                raise ProviderError(self.name, "http_error", f"HTTP {code}", code)
        raise ProviderError(self.name, "unavailable", "exhausted retries")

    async def search(self, query: str, filters: dict, limit: int, cursor: str | None = None) -> SearchPage:
        raise Unsupported(self.name, Capability.SEARCH)

    async def lookup_identifier(self, doi: str) -> PaperRecord | None:
        raise Unsupported(self.name, Capability.LOOKUP_IDENTIFIER)

    async def locate_full_text(self, record: PaperRecord) -> PaperRecord:
        raise Unsupported(self.name, Capability.LOCATE_FULL_TEXT)

    async def report_quota(self) -> Quota:
        raise Unsupported(self.name, Capability.REPORT_QUOTA)
