"""Identity verification fallback: a Crossref provider failure falls back to DataCite like a missing
record does, provider identity survives in the posted evidence, and only transient failures retry."""

from __future__ import annotations

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from rp_research.adapters import base as adapter_base
from rp_research.features import literature as lit

PAPER = {"id": "p1", "doi": "10.5555/zenodo.123", "title": "A Provenance Study of Reproducibility", "year": 2020}

DATACITE_OK = {"data": {"attributes": {
    "titles": [{"title": "A Provenance Study of Reproducibility"}], "creators": [{"name": "Rupprecht, Lukas"}],
    "publicationYear": 2020, "publisher": "VLDB Endowment", "types": {"resourceTypeGeneral": "Text"},
    "url": "https://example.org/paper.pdf", "rightsList": []}}}


class FakeApi:
    def __init__(self, papers: dict[str, dict]):
        self.papers = papers
        self.posts: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, path: str, **params):
        return self.papers[path.rsplit("/", 1)[-1]]

    async def post(self, path: str, body: dict):
        self.posts.append((path, body))
        return {}


@pytest.fixture
def no_sleep(monkeypatch):
    async def fake(seconds):
        pass

    monkeypatch.setattr(adapter_base, "_sleep", fake)


@pytest.fixture
def reset_transport():
    yield
    adapter_base.use_transport(None)


def route(crossref, datacite):
    """Route the mock transport by registry; factories build a fresh response per request."""
    calls = {"crossref": 0, "datacite": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        which = "datacite" if "datacite" in str(request.url) else "crossref"
        calls[which] += 1
        return (datacite if which == "datacite" else crossref)()

    adapter_base.use_transport(httpx.MockTransport(handler))
    return calls


def wire(monkeypatch, papers: dict[str, dict]) -> FakeApi:
    api = FakeApi(papers)
    monkeypatch.setattr(lit, "ApiClient", lambda task_id: api)
    return api


async def test_crossref_failure_falls_back_to_datacite(no_sleep, reset_transport, monkeypatch):
    route(lambda: httpx.Response(503), lambda: httpx.Response(200, json=DATACITE_OK))
    api = wire(monkeypatch, {"p1": dict(PAPER)})
    out = await lit.verify_identities("t1", "proj", ["p1"])
    assert out == {"p1": "verified"}
    (_, body), = api.posts
    assert body["status"] == "verified" and body["evidence"]["source"] == "datacite"
    (err,) = body["evidence"]["provider_errors"]
    assert err["provider"] == "crossref" and err["kind"] == "unavailable" and err["status"] == 503


async def test_stopped_crossref_is_not_contacted_again_and_datacite_serves_the_rest(no_sleep, reset_transport, monkeypatch):
    calls = route(lambda: httpx.Response(403), lambda: httpx.Response(200, json=DATACITE_OK))
    api = wire(monkeypatch, {"p1": dict(PAPER), "p2": {**PAPER, "id": "p2"}})
    out = await lit.verify_identities("t1", "proj", ["p1", "p2"])
    assert out == {"p1": "verified", "p2": "verified"}
    assert calls["crossref"] == 1 and calls["datacite"] == 2  # stop-after-403 honoured across the loop
    for _, body in api.posts:
        assert body["evidence"]["provider_errors"][0]["provider"] == "crossref"
        assert body["evidence"]["provider_errors"][0]["kind"] == "access_denied"


async def test_unregistered_in_both_registries_is_still_not_found(no_sleep, reset_transport, monkeypatch):
    route(lambda: httpx.Response(404), lambda: httpx.Response(404))
    api = wire(monkeypatch, {"p1": dict(PAPER)})
    out = await lit.verify_identities("t1", "proj", ["p1"])
    assert out == {"p1": "not_found"}
    (_, body), = api.posts
    assert "fabricated" in body["evidence"]["reason"]


async def test_transient_failure_without_a_record_is_retried_not_not_found(no_sleep, reset_transport, monkeypatch):
    route(lambda: httpx.Response(503), lambda: httpx.Response(404))
    api = wire(monkeypatch, {"p1": dict(PAPER)})
    with pytest.raises(ApplicationError) as exc:
        await lit.verify_identities("t1", "proj", ["p1"])
    assert not exc.value.non_retryable and exc.value.type == "unavailable" and "crossref" in str(exc.value)
    (_, body), = api.posts  # the interim record is posted before the retry is requested
    assert body["status"] == "unavailable" and body["evidence"]["retryable"] is True
    assert body["evidence"]["provider_errors"][0]["provider"] == "crossref"


async def test_nonretryable_failure_without_a_record_is_terminal_unavailable(no_sleep, reset_transport, monkeypatch):
    route(lambda: httpx.Response(400), lambda: httpx.Response(404))
    api = wire(monkeypatch, {"p1": dict(PAPER)})
    out = await lit.verify_identities("t1", "proj", ["p1"])
    assert out == {"p1": "unavailable"}
    (_, body), = api.posts
    assert body["evidence"]["retryable"] is False
    assert body["evidence"]["provider_errors"][0] == {"provider": "crossref", "kind": "http_error", "status": 400,
                                                      "error": "crossref: http_error: HTTP 400"}
