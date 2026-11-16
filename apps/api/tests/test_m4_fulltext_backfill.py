"""Backfill for pre-label papers: unlabelled locations get a kind from the shared classifier, ``located`` is
kept only for papers with a file link, and verdicts set by the fetch step are never touched. Repeatable."""

from __future__ import annotations

import uuid

from conftest import make_project, make_user

from rp_api.services.backfills import backfill_fulltext_location_kinds

FILE = {"url": "https://repo.example.org/paper.pdf", "kind": "file", "source": "openaire"}
LANDING = {"url": "https://doi.org/10.1234/landing", "kind": "landing_page", "source": "openaire"}
PUBLISHER = {"url": "https://publisher.example.org/article/1", "kind": "publisher_link", "source": "crossref"}
LEGACY_PDF = {"url": "http://arxiv.org/pdf/2006.12117", "source": "openaire"}  # unlabelled, pre-label era
LEGACY_DOI = {"url": "https://dx.doi.org/10.1234/x", "source": "openaire"}


async def seed(tenant_id: str, project_id: str, title: str, locations: list[dict], status: str) -> None:
    from rp_api.db.engine import session_scope
    from rp_api.db.models.literature import TenantPaperRecord

    async with session_scope("system") as db:
        db.add(TenantPaperRecord(tenant_id=uuid.UUID(tenant_id), project_id=uuid.UUID(project_id), title=title,
                                 added_by="test", fulltext_locations=locations, fulltext_status=status))
        await db.commit()


async def papers_by_title(u, project_id: str) -> dict[str, dict]:
    items = (await u.get(f"/v1/projects/{project_id}/papers")).json()["items"]
    return {p["title"]: p for p in items}


async def test_backfill_labels_links_and_fixes_located(client):
    u = await make_user(client)
    p = await make_project(u)
    await seed(u.tenant_id, p["id"], "file-labelled", [LANDING, FILE], "located")
    await seed(u.tenant_id, p["id"], "landing-only", [LANDING, PUBLISHER], "located")
    await seed(u.tenant_id, p["id"], "legacy-doi", [LEGACY_DOI], "located")
    await seed(u.tenant_id, p["id"], "legacy-pdf", [LEGACY_PDF], "located")
    await seed(u.tenant_id, p["id"], "legacy-none", [LEGACY_PDF], "none")
    await seed(u.tenant_id, p["id"], "fetched-parsed", [LEGACY_DOI], "parsed")
    await seed(u.tenant_id, p["id"], "fetched-inaccessible", [LANDING], "inaccessible")

    report = (await backfill_fulltext_location_kinds(project_id=uuid.UUID(p["id"]))).as_dict()
    assert report == {"papers_scanned": 7, "locations_labelled": 4, "downgraded_to_none": 2, "upgraded_to_located": 1}

    papers = await papers_by_title(u, p["id"])
    # A labelled file link keeps the paper located; landing pages and publisher links do not.
    assert papers["file-labelled"]["fulltext_status"] == "located"
    assert papers["landing-only"]["fulltext_status"] == "none"
    # Unlabelled legacy links are classified: a DOI page loses located, a real PDF link keeps (or gains) it.
    assert papers["legacy-doi"]["fulltext_status"] == "none"
    assert papers["legacy-doi"]["fulltext_locations"][0]["kind"] == "landing_page"
    assert papers["legacy-pdf"]["fulltext_status"] == "located"
    assert papers["legacy-pdf"]["fulltext_locations"][0]["kind"] == "file"
    assert papers["legacy-none"]["fulltext_status"] == "located"
    # Verdicts from the fetch step are untouched, but their locations still get labels.
    assert papers["fetched-parsed"]["fulltext_status"] == "parsed"
    assert papers["fetched-parsed"]["fulltext_locations"][0]["kind"] == "landing_page"
    assert papers["fetched-inaccessible"]["fulltext_status"] == "inaccessible"


async def test_backfill_is_repeatable(client):
    u = await make_user(client)
    p = await make_project(u)
    await seed(u.tenant_id, p["id"], "legacy", [LEGACY_DOI, LEGACY_PDF], "located")
    first = (await backfill_fulltext_location_kinds(project_id=uuid.UUID(p["id"]))).as_dict()
    assert first["locations_labelled"] >= 2
    before = await papers_by_title(u, p["id"])
    second = (await backfill_fulltext_location_kinds(project_id=uuid.UUID(p["id"]))).as_dict()
    assert second["locations_labelled"] == second["downgraded_to_none"] == second["upgraded_to_located"] == 0
    assert await papers_by_title(u, p["id"]) == before
