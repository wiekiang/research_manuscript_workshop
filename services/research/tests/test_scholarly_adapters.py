"""Provider adapter contract tests against recorded OpenAIRE/Crossref responses and synthetic failure modes."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rp_contracts.literature import Capability, rights_for
from rp_research.adapters import base as adapter_base
from rp_research.adapters.base import Disabled, ProviderError
from rp_research.adapters.providers import (
    ConnectedAccountAdapter,
    CoreAdapter,
    CrossrefAdapter,
    OpenAireAdapter,
)
from rp_research.features.literature import identity_verdict

FIX = Path(__file__).parent / "fixtures" / "providers"


def recorded(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "openaire" in url and "pid=" in url:
        return httpx.Response(200, json=json.loads((FIX / "openaire_pid.json").read_text()))
    if "openaire" in url:
        return httpx.Response(200, json=json.loads((FIX / "openaire_search.json").read_text()))
    if "crossref" in url and "/works/10.14778" in url:
        return httpx.Response(200, json=json.loads((FIX / "crossref_work.json").read_text()))
    if "crossref" in url and "/works/" in url:
        return httpx.Response(404, text="Resource not found.")
    if "crossref" in url:
        return httpx.Response(200, json=json.loads((FIX / "crossref_search.json").read_text()))
    return httpx.Response(500)


@pytest.fixture
def transport():
    adapter_base.use_transport(httpx.MockTransport(recorded))
    yield
    adapter_base.use_transport(None)


async def test_openaire_search_normalization(transport):
    page = await OpenAireAdapter().search("provenance reproducibility", {"year_from": 2018}, 5)
    assert page.total == 195 and len(page.records) == 5
    r = next(x for x in page.records if x.doi == "10.14778/3415478.3415556")
    assert r.title and r.year == 2020 and r.metadata_license.startswith("CC-BY")
    assert r.fulltext and all(loc.source == "openaire" for loc in r.fulltext)
    assert page.next_cursor == "2"


async def test_crossref_search_lookup_and_not_found(transport):
    page = await CrossrefAdapter().search("provenance", {}, 5)
    assert len(page.records) == 5 and page.records[0].metadata_license.startswith("CC0")
    assert all(r.abstract_rights == "publisher_copyright" for r in page.records)
    work = await CrossrefAdapter().lookup_identifier("https://doi.org/10.14778/3415478.3415556")
    assert work and "reproducibility" in work.title.lower()
    assert await CrossrefAdapter().lookup_identifier("10.9999/fabricated.doi.2025.00001") is None


async def test_identity_verdicts(transport):
    work = await CrossrefAdapter().lookup_identifier("10.14778/3415478.3415556")
    ok, _ = identity_verdict({"title": work.title, "year": 2020}, work)
    assert ok == "verified"
    bad, ev = identity_verdict({"title": "Quantum chromodynamics of soft matter", "year": 2020}, work)
    assert bad == "mismatch" and ev["title_similarity"] < 0.6
    missing, ev = identity_verdict({"title": "Anything"}, None)
    assert missing == "not_found" and "fabricated" in ev["reason"]


@pytest.mark.parametrize("status,kind,retryable", [(401, "access_denied", False), (403, "access_denied", False),
                                                   (402, "payment_required", False), (429, "rate_limited", True),
                                                   (503, "unavailable", True)])
async def test_http_failures_are_classified(status, kind, retryable):
    adapter_base.use_transport(httpx.MockTransport(lambda r: httpx.Response(status, headers={"retry-after": "7"})))
    try:
        with pytest.raises(ProviderError) as exc:
            await CrossrefAdapter().search("x", {}, 5)
        assert exc.value.kind == kind and exc.value.retryable == retryable
        if status == 429:
            assert exc.value.retry_after == 7
    finally:
        adapter_base.use_transport(None)


async def test_partial_response_is_flagged():
    body = json.loads((FIX / "crossref_search.json").read_text())
    body["message"]["items"][0]["title"] = []
    adapter_base.use_transport(httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        page = await CrossrefAdapter().search("x", {}, 5)
        assert page.partial and len(page.records) == 4
    finally:
        adapter_base.use_transport(None)


async def test_capabilities_are_explicit_and_gated_providers_refuse():
    assert not CrossrefAdapter().supports(Capability.RETRIEVE_PERMITTED_FULL_TEXT)
    with pytest.raises(Disabled):
        await CoreAdapter().search("x", {}, 5)
    with pytest.raises(Disabled):
        await ConnectedAccountAdapter("elicit", "blocked", credential="user-key").search("x", {}, 5)
    with pytest.raises(Disabled):
        await ConnectedAccountAdapter("consensus", "cleared", credential=None).search("x", {}, 5)


def test_item_level_rights():
    assert rights_for("https://creativecommons.org/licenses/by/4.0/", True).model_use_permitted
    nc = rights_for("CC BY-NC 4.0", True)
    assert nc.storage_permitted and not nc.model_use_permitted
    oa = rights_for(None, True)
    assert not oa.storage_permitted and "do not store" in oa.basis
    assert not rights_for("All rights reserved", False).storage_permitted


async def test_core_adapter_parses_the_published_v3_schema_and_stays_gated():
    import json as _json
    from pathlib import Path as _Path

    data = _json.loads((_Path(__file__).parent / "fixtures/providers/core_search_spec.json").read_text())
    seen = {}

    def web(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, json=data)

    with pytest.raises(Disabled):
        await CoreAdapter(enabled=False, api_key="k").search("provenance", {}, 2)
    adapter_base.use_transport(httpx.MockTransport(web))
    try:
        page = await CoreAdapter(enabled=True, api_key="test-key").search("provenance", {}, 2)
    finally:
        adapter_base.use_transport(None)
    assert seen["url"].startswith("https://api.core.ac.uk/v3/search/works/?q=provenance") and seen["auth"] == "Bearer test-key"
    assert page.total == 2 and page.next_cursor is None
    a, b = page.records
    assert a.doi == "10.14778/3415478.3415556" and a.authors == ["Lukas Rupprecht", "James C. Davis"] and a.year == 2020
    assert a.fulltext[0].url.endswith("1001.pdf") and a.attribution.startswith("Data provided by CORE")
    assert b.fulltext == [] and b.doi is None
