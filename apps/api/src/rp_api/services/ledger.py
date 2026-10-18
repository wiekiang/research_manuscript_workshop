"""Research Contribution Ledger (separate from the approval engine).

Captures attributable substantive actions automatically. Researchers can add context, correct an entry
(the original is preserved and marked corrected) and verify their own record at H4. Approval clicks are never
written here. A ledger is evidence for author review, not an authorship certification.
"""

from __future__ import annotations

import difflib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import LedgerCategory

from ..db.base import utcnow
from ..db.models.core import ContributionLedgerEntry, Project
from ..errors import forbidden, not_found, unprocessable
from ..security.tokens import Principal
from .common import audit


def text_diff(before: str | None, after: str | None, label: str = "content") -> str | None:
    if (before or "") == (after or ""):
        return None
    return "".join(difflib.unified_diff((before or "").splitlines(True), (after or "").splitlines(True),
                                        fromfile=f"{label} (before)", tofile=f"{label} (after)", n=2))[:20000]


async def capture(
    db: AsyncSession, actor: Principal, project: Project, category: LedgerCategory, summary: str, *,
    source_action: str, diff: str | None = None, artifact_id: uuid.UUID | None = None, source_ref: str | None = None,
    rationale: str | None = None, rationale_requested: bool | None = None,
) -> ContributionLedgerEntry | None:
    """Auto-capture a human action. Service/agent actions are never recorded as human contributions."""
    if actor.kind != "user" or actor.user_id is None:
        return None
    needs_context = rationale_requested if rationale_requested is not None else (not rationale and diff is None)
    entry = ContributionLedgerEntry(
        tenant_id=project.tenant_id, project_id=project.id, user_id=actor.user_id, category=category.value,
        summary=summary[:2000], diff=diff, artifact_id=artifact_id, source_action=source_action, source_ref=source_ref,
        auto_captured=True, rationale=rationale, rationale_requested=needs_context,
    )
    db.add(entry)
    await db.flush()
    return entry


async def add_manual(db: AsyncSession, actor: Principal, project: Project, category: LedgerCategory, summary: str,
                     rationale: str | None, artifact_id: uuid.UUID | None = None) -> ContributionLedgerEntry:
    if not summary.strip():
        raise unprocessable("summary_required", "describe the contribution")
    entry = ContributionLedgerEntry(
        tenant_id=project.tenant_id, project_id=project.id, user_id=actor.user_id, category=category.value,
        summary=summary, rationale=rationale, artifact_id=artifact_id, source_action="manual_entry",
        auto_captured=False,
    )
    db.add(entry)
    await db.flush()
    await audit(db, actor, "ledger.manual_entry", project_id=project.id, resource_type="ledger_entry", resource_id=entry.id)
    return entry


async def _entry(db: AsyncSession, project_id: uuid.UUID, entry_id: uuid.UUID) -> ContributionLedgerEntry:
    e = (await db.execute(select(ContributionLedgerEntry).where(
        ContributionLedgerEntry.id == entry_id, ContributionLedgerEntry.project_id == project_id))).scalar_one_or_none()
    if e is None:
        raise not_found("ledger entry")
    return e


async def correct(db: AsyncSession, actor: Principal, project: Project, entry_id: uuid.UUID, summary: str | None,
                  category: LedgerCategory | None, rationale: str | None) -> ContributionLedgerEntry:
    old = await _entry(db, project.id, entry_id)
    if old.user_id != actor.user_id:
        raise forbidden("researchers correct only their own contribution record")
    new = ContributionLedgerEntry(
        tenant_id=old.tenant_id, project_id=old.project_id, user_id=old.user_id,
        category=(category or LedgerCategory(old.category)).value, summary=summary or old.summary, diff=old.diff,
        artifact_id=old.artifact_id, source_action=old.source_action, source_ref=old.source_ref,
        auto_captured=old.auto_captured, rationale=rationale if rationale is not None else old.rationale,
        rationale_requested=False, correction_of=old.id,
    )
    old.status = "corrected"
    db.add(new)
    await db.flush()
    await audit(db, actor, "ledger.corrected", project_id=project.id, resource_type="ledger_entry", resource_id=new.id,
                details={"correction_of": str(old.id)})
    return new


async def add_context(db: AsyncSession, actor: Principal, project: Project, entry_id: uuid.UUID,
                      rationale: str) -> ContributionLedgerEntry:
    e = await _entry(db, project.id, entry_id)
    if e.user_id != actor.user_id:
        raise forbidden("only the contributor can explain this entry")
    e.rationale = rationale
    e.rationale_requested = False
    return e


async def verify_own(db: AsyncSession, actor: Principal, project: Project) -> int:
    rows = list((await db.execute(select(ContributionLedgerEntry).where(
        ContributionLedgerEntry.project_id == project.id, ContributionLedgerEntry.user_id == actor.user_id,
        ContributionLedgerEntry.status == "recorded"))).scalars())
    now = utcnow()
    for r in rows:
        r.status = "verified"
        r.verified_by = actor.user_id
        r.verified_at = now
    await audit(db, actor, "ledger.verified", project_id=project.id, details={"entries": len(rows)})
    return len(rows)


async def has_substantive_contribution(db: AsyncSession, project_id: uuid.UUID) -> bool:
    substantive = {c.value for c in LedgerCategory} - {LedgerCategory.OTHER.value}
    row = (await db.execute(select(ContributionLedgerEntry.id).where(
        ContributionLedgerEntry.project_id == project_id, ContributionLedgerEntry.category.in_(substantive),
        ContributionLedgerEntry.status.in_(["recorded", "verified"])).limit(1))).first()
    return row is not None
