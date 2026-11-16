"""Safe, repeatable data backfills (run via ``rp-api backfill-fulltext-kinds``).

Papers saved before full-text locations carried a ``kind`` label can be marked ``located`` on the strength of a
landing page or publisher link. This backfill labels unlabelled locations with the shared classifier and then
recomputes ``located``/``none`` from the labels. Statuses set by later fetch steps (``retrieved``, ``parsed``,
``not_permitted``, ``inaccessible``) are never touched. Running it again is a no-op.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import func, select

from rp_contracts.literature import classify_location

from ..db.engine import session_scope
from ..db.models.literature import TenantPaperRecord
from ..features.literature import located_status

BATCH = 500


@dataclass
class FulltextBackfillReport:
    papers_scanned: int = 0
    locations_labelled: int = 0
    downgraded_to_none: int = 0
    upgraded_to_located: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def _labelled(locations: list[dict]) -> tuple[list[dict], int]:
    out, added = [], 0
    for loc in locations:
        loc = dict(loc or {})
        if not loc.get("kind"):
            loc["kind"] = classify_location(loc.get("url") or "", loc.get("content_type"))
            added += 1
        out.append(loc)
    return out, added


async def backfill_fulltext_location_kinds(project_id=None) -> FulltextBackfillReport:
    """Label stored full-text locations and fix ``located``/``none`` statuses, across all tenants by default."""
    report = FulltextBackfillReport()
    last = None
    while True:
        async with session_scope("system") as db:
            q = (select(TenantPaperRecord).where(func.jsonb_array_length(TenantPaperRecord.fulltext_locations) > 0)
                 .order_by(TenantPaperRecord.id).limit(BATCH))
            if project_id is not None:
                q = q.where(TenantPaperRecord.project_id == project_id)
            if last is not None:
                q = q.where(TenantPaperRecord.id > last)
            papers = list((await db.execute(q)).scalars())
            if not papers:
                return report
            for p in papers:
                report.papers_scanned += 1
                locations, added = _labelled(p.fulltext_locations or [])
                if added:
                    report.locations_labelled += added
                    p.fulltext_locations = locations  # reassign: in-place JSONB edits are not tracked
                if p.fulltext_status in ("none", "located"):
                    status = located_status(locations)
                    if status != p.fulltext_status:
                        report.downgraded_to_none += status == "none"
                        report.upgraded_to_located += status == "located"
                        p.fulltext_status = status
            last = papers[-1].id
            await db.commit()
