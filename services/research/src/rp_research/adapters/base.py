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
        self.kind = kind  # rate_limited | unavailable | access_denied | payment_required | not_found | bad_response
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


def use_transport(t: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject recorded fixtures through an httpx transport."""
    global _transport
    _transport = t


class Adapter:
    name = "base"
    capabilities: dict[Capability, bool] = {}

    def supports(self, cap: Capability) -> bool:
        return self.capabilities.get(cap, False)

    def _require(self, cap: Capability) -> None:
        if not self.supports(cap):
            raise Unsupported(self.name, cap)

    async def _get(self, url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
        async with httpx.AsyncClient(transport=_transport, timeout=30.0, headers={"User-Agent": USER_AGENT,
                                                                                **(headers or {})}) as c:
            for attempt in range(3):
                try:
                    r = await c.get(url, params=params)
                except httpx.TimeoutException as exc:
                    if attempt == 2:
                        raise ProviderError(self.name, "unavailable", "timeout") from exc
                    await asyncio.sleep(1 + attempt)
                    continue
                except httpx.HTTPError as exc:
                    raise ProviderError(self.name, "unavailable", str(exc)) from exc
                if r.status_code == 429:
                    ra = r.headers.get("retry-after")
                    raise ProviderError(self.name, "rate_limited", "rate limited", 429, int(ra) if ra and ra.isdigit() else 30)
                if r.status_code in (401, 403):
                    raise ProviderError(self.name, "access_denied", f"HTTP {r.status_code}", r.status_code)
                if r.status_code == 402:
                    raise ProviderError(self.name, "payment_required", "HTTP 402", 402)
                if r.status_code == 404:
                    raise ProviderError(self.name, "not_found", "not found", 404)
                if r.status_code >= 500:
                    if attempt == 2:
                        raise ProviderError(self.name, "unavailable", f"HTTP {r.status_code}", r.status_code)
                    await asyncio.sleep(1 + attempt)
                    continue
                return r
        raise ProviderError(self.name, "unavailable", "exhausted retries")

    async def search(self, query: str, filters: dict, limit: int, cursor: str | None = None) -> SearchPage:
        raise Unsupported(self.name, Capability.SEARCH)

    async def lookup_identifier(self, doi: str) -> PaperRecord | None:
        raise Unsupported(self.name, Capability.LOOKUP_IDENTIFIER)

    async def locate_full_text(self, record: PaperRecord) -> PaperRecord:
        raise Unsupported(self.name, Capability.LOCATE_FULL_TEXT)

    async def report_quota(self) -> Quota:
        raise Unsupported(self.name, Capability.REPORT_QUOTA)
