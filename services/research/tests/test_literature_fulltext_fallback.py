"""Full-text discovery boundary: OpenAIRE provider failures keep their identity and retry classification
instead of being swallowed before the fallback to stored locations."""

from __future__ import annotations

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from rp_research.adapters import base as adapter_base
from rp_research.features import literature as lit
from rp_research.fetch.fetcher import FetchFailed


class FakeApi:
    def __init__(self, paper: dict):
        self.paper = paper
        self.posts: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, path: str, **params):
        return self.paper

    async def post(self, path: str, body: dict):
        self.posts.append((path, body))
        return {}


class FailingFetcher:
    async def fetch(self, url: str, **kw):
        raise FetchFailed("http_error", url, retryable=False, status=404)


PAPER = {"id": "p1", "doi": "10.14778/3415478.3415556", "title": "Provenance", "open_access": True,
         "license": "https://creativecommons.org/licenses/by/4.0/", "fulltext_locations": []}


@pytest.fixture
def no_sleep(monkeypatch):
    async def fake(seconds):
        pass

    monkeypatch.setattr(adapter_base, "_sleep", fake)


def openaire_failing(status: int):
    adapter_base.use_transport(httpx.MockTransport(lambda r: httpx.Response(status)))


@pytest.fixture
def reset_transport():
    yield
    adapter_base.use_transport(None)


def wire(monkeypatch, paper: dict) -> FakeApi:
    api = FakeApi(paper)
    monkeypatch.setattr(lit, "ApiClient", lambda task_id: api)
    monkeypatch.setattr(lit, "fetcher", lambda: FailingFetcher())
    return api


async def test_retryable_discovery_failure_with_no_fallback_raises_retryable(no_sleep, reset_transport, monkeypatch):
    openaire_failing(503)
    api = wire(monkeypatch, dict(PAPER))
    with pytest.raises(ApplicationError) as exc:
        await lit.paper_fetch_permitted("t1", "proj", "p1")
    assert not exc.value.non_retryable and exc.value.type == "unavailable"
    assert "openaire" in str(exc.value)
    assert api.posts == []  # no terminal record for a transient outage


async def test_retryable_discovery_failure_falls_back_to_stored_locations(no_sleep, reset_transport, monkeypatch):
    openaire_failing(503)
    paper = {**PAPER, "fulltext_locations": [{"url": "https://host.example.org/a.pdf"}]}
    api = wire(monkeypatch, paper)
    res = await lit.paper_fetch_permitted("t1", "proj", "p1")
    assert res == {"status": "inaccessible"}
    (_, body), = api.posts
    assert body["status"] == "inaccessible"
    assert "openaire" in body["detail"] and "unavailable" in body["detail"]  # reported before falling back


async def test_nonretryable_discovery_failure_is_reported_not_raised(no_sleep, reset_transport, monkeypatch):
    openaire_failing(403)
    api = wire(monkeypatch, dict(PAPER))
    res = await lit.paper_fetch_permitted("t1", "proj", "p1")
    assert res == {"status": "inaccessible"}
    (_, body), = api.posts
    assert "openaire" in body["detail"] and "access_denied" in body["detail"]


async def test_rate_limited_discovery_error_carries_retry_delay(no_sleep, reset_transport):
    adapter_base.use_transport(httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "3600"})))
    with pytest.raises(adapter_base.ProviderError) as exc:
        await lit.OpenAireAdapter().lookup_identifier("10.14778/3415478.3415556")
    err = lit.app_error(exc.value)
    assert not err.non_retryable and err.type == "rate_limited"
    assert err.next_retry_delay is not None and err.next_retry_delay.total_seconds() == 3600
    assert "openaire" in str(err) and err.details[0]["provider"] == "openaire"
