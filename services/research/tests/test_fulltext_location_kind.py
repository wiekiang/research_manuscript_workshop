"""Full-text location labels: the shared classifier, adapter labelling, and the fetch rule that tries file
links first and never stores a landing page as full text (including unlabelled legacy locations)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from rp_contracts.literature import FullTextLocation, classify_location, location_kind
from rp_research.adapters import base as adapter_base
from rp_research.adapters.providers import CoreAdapter, CrossrefAdapter, OpenAireAdapter
from rp_research.features import literature as lit

FIX = Path(__file__).parent / "fixtures" / "providers"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
HTML = b"<!doctype html><html><head><title>Article</title></head><body>Landing</body></html>"


@pytest.mark.parametrize("url,ct,kind", [
    ("http://arxiv.org/pdf/2006.12117", None, "file"),
    ("https://arxiv.org/abs/2006.12117", None, "landing_page"),
    ("https://doi.org/10.14778/3415478.3415556", None, "landing_page"),
    ("https://dx.doi.org/10.5281/zenodo.19389219", None, "landing_page"),
    ("https://hdl.handle.net/11590/387315", None, "landing_page"),
    ("https://dblp.org/rec/journals/pvldb/RupprechtDAGB20.html", None, "landing_page"),
    ("https://zenodo.org/records/19389220", None, "landing_page"),
    ("https://zenodo.org/records/19389220/files/paper.pdf", None, "file"),
    ("https://link.springer.com/content/pdf/10.1007/978-3-030-80960-7_17", None, "file"),
    ("https://dl.acm.org/doi/pdf/10.14778/3415478.3415556", None, "file"),
    ("https://publisher.example.org/article/123", "application/pdf", "file"),
    ("https://publisher.example.org/article/123", None, "landing_page"),
])
def test_classify_location(url, ct, kind):
    assert classify_location(url, ct) == kind


def test_unlabelled_locations_default_to_landing_page():
    assert FullTextLocation(url="https://x.example.org/a.pdf", source="t").kind == "landing_page"
    assert location_kind({"url": "https://x.example.org/a.pdf"}) == "file"  # legacy dict: classified by rule
    assert location_kind({"url": "https://doi.org/10.1/x"}) == "landing_page"
    assert location_kind({"url": "https://doi.org/10.1/x", "kind": "file"}) == "file"  # explicit label wins


async def test_openaire_fixture_labels_only_the_arxiv_pdf_as_a_file():
    body = json.loads((FIX / "openaire_search.json").read_text())
    adapter_base.use_transport(httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        page = await OpenAireAdapter().search("x", {}, 5)
    finally:
        adapter_base.use_transport(None)
    files = {loc.url for r in page.records for loc in r.fulltext if loc.kind == "file"}
    assert files == {"http://arxiv.org/pdf/2006.12117"}


def test_crossref_and_core_labels():
    cr = CrossrefAdapter()._record({"DOI": "10.1/x", "title": ["T"], "link": [
        {"URL": "https://pub.example.org/article/1", "intended-application": "unspecified"},
        {"URL": "https://pub.example.org/x", "content-type": "application/pdf", "intended-application": "text-mining"}]})
    assert [loc.kind for loc in cr.fulltext] == ["publisher_link", "file"]
    core = CoreAdapter(enabled=False, api_key="k")._record({"id": 1, "title": "T", "download_url": "https://core.ac.uk/d/1"})
    assert core.fulltext[0].kind == "file"


class FakeApi:
    def __init__(self, paper):
        self.paper, self.posts, self.published = paper, [], []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, path, **params):
        return self.paper

    async def post(self, path, body):
        self.posts.append(body)
        return {}

    async def publish(self, project_id, kind, data, media_type, h, **kw):
        self.published.append((kw["metadata"]["url"], media_type))
        return SimpleNamespace(artifact_id="art-1")


class ScriptedFetcher:
    def __init__(self, pages):
        self.pages, self.seen = pages, []

    async def fetch(self, url, **kw):
        self.seen.append(url)
        data, mt = self.pages[url]
        return SimpleNamespace(content=data, media_type=mt, final_url=url)


def wire(monkeypatch, locations, pages):
    paper = {"id": "p1", "title": "T", "doi": None, "license": "https://creativecommons.org/licenses/by/4.0/",
             "open_access": True, "fulltext_locations": locations}
    api, f = FakeApi(paper), ScriptedFetcher(pages)
    monkeypatch.setattr(lit, "ApiClient", lambda task_id: api)
    monkeypatch.setattr(lit, "fetcher", lambda: f)
    return api, f


async def test_file_links_are_tried_first(monkeypatch):
    landing = {"url": "https://doi.org/10.1/x", "kind": "landing_page", "source": "openaire"}
    pdf = {"url": "https://repo.example.org/x.pdf", "kind": "file", "source": "openaire"}
    api, f = wire(monkeypatch, [landing, pdf], {pdf["url"]: (PDF, "application/pdf"), landing["url"]: (HTML, "text/html")})
    res = await lit.paper_fetch_permitted("t", "proj", "p1")
    assert res["artifact_id"] == "art-1" and f.seen == [pdf["url"]]


async def test_landing_page_html_is_not_saved_as_full_text(monkeypatch):
    landing = {"url": "https://doi.org/10.1/x", "kind": "landing_page", "source": "openaire"}
    api, f = wire(monkeypatch, [landing], {landing["url"]: (HTML, "text/html")})
    assert await lit.paper_fetch_permitted("t", "proj", "p1") == {"status": "inaccessible"}
    assert api.published == []
    assert api.posts[-1]["status"] == "inaccessible" and "landing page" in api.posts[-1]["detail"]


async def test_landing_page_that_serves_a_pdf_is_saved(monkeypatch):
    landing = {"url": "https://doi.org/10.1/x", "kind": "landing_page", "source": "openaire"}
    api, _ = wire(monkeypatch, [landing], {landing["url"]: (PDF, "application/pdf")})
    res = await lit.paper_fetch_permitted("t", "proj", "p1")
    assert res["artifact_id"] == "art-1" and api.published == [(landing["url"], "application/pdf")]


async def test_html_from_a_labelled_file_link_is_saved(monkeypatch):
    loc = {"url": "https://repo.example.org/fulltext/1", "kind": "file", "source": "core"}
    api, _ = wire(monkeypatch, [loc], {loc["url"]: (HTML, "text/html")})
    assert (await lit.paper_fetch_permitted("t", "proj", "p1"))["artifact_id"] == "art-1"


async def test_unlabelled_legacy_locations_stay_safe(monkeypatch):
    old_landing = {"url": "https://dx.doi.org/10.1/x", "source": "openaire"}  # stored before labels existed
    old_pdf = {"url": "http://arxiv.org/pdf/2006.12117", "source": "openaire"}
    api, f = wire(monkeypatch, [old_landing], {old_landing["url"]: (HTML, "text/html")})
    assert await lit.paper_fetch_permitted("t", "proj", "p1") == {"status": "inaccessible"} and api.published == []
    api, f = wire(monkeypatch, [old_landing, old_pdf], {old_pdf["url"]: (PDF, "application/pdf"),
                                                        old_landing["url"]: (HTML, "text/html")})
    assert (await lit.paper_fetch_permitted("t", "proj", "p1"))["artifact_id"] == "art-1"
    assert f.seen == [old_pdf["url"]]
