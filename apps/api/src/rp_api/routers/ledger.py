from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from rp_contracts.enums import LedgerCategory

from ..db.models.core import ContributionLedgerEntry, User
from ..deps import EDIT_ROLES, Ctx, project_for, user_ctx
from ..services import ledger

router = APIRouter(prefix="/projects/{project_id}/contribution-ledger", tags=["contribution-ledger"])


class ManualIn(BaseModel):
    category: LedgerCategory
    summary: str = Field(min_length=3, max_length=4000)
    rationale: str | None = Field(default=None, max_length=8000)


class CorrectIn(BaseModel):
    summary: str | None = Field(default=None, max_length=4000)
    category: LedgerCategory | None = None
    rationale: str | None = Field(default=None, max_length=8000)


class ContextIn(BaseModel):
    rationale: str = Field(min_length=3, max_length=8000)


def entry_out(e: ContributionLedgerEntry, name: str | None = None) -> dict:
    return {"id": str(e.id), "user_id": str(e.user_id), "contributor": name, "category": e.category, "summary": e.summary,
            "diff": e.diff, "artifact_id": str(e.artifact_id) if e.artifact_id else None, "source_action": e.source_action,
            "auto_captured": e.auto_captured, "rationale": e.rationale, "rationale_requested": e.rationale_requested,
            "status": e.status, "correction_of": str(e.correction_of) if e.correction_of else None,
            "verified_at": e.verified_at, "created_at": e.created_at}


@router.get("")
async def list_entries(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(ContributionLedgerEntry, User.display_name).join(
        User, User.id == ContributionLedgerEntry.user_id).where(ContributionLedgerEntry.project_id == project_id)
        .order_by(ContributionLedgerEntry.created_at.desc()))).all()
    return {"items": [entry_out(e, n) for e, n in rows],
            "note": "This record is evidence for author review, not an authorship certification. Approval clicks are "
                    "recorded separately in the approval engine."}


@router.post("", status_code=201)
async def add_entry(project_id: uuid.UUID, body: ManualIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    e = await ledger.add_manual(ctx.db, ctx.principal, project, body.category, body.summary, body.rationale)
    await ctx.db.commit()
    return entry_out(e)


@router.post("/{entry_id}/correct", status_code=201)
async def correct(project_id: uuid.UUID, entry_id: uuid.UUID, body: CorrectIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    e = await ledger.correct(ctx.db, ctx.principal, project, entry_id, body.summary, body.category, body.rationale)
    await ctx.db.commit()
    return entry_out(e)


@router.post("/{entry_id}/context")
async def context(project_id: uuid.UUID, entry_id: uuid.UUID, body: ContextIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    e = await ledger.add_context(ctx.db, ctx.principal, project, entry_id, body.rationale)
    await ctx.db.commit()
    return entry_out(e)


@router.post("/verify")
async def verify(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    n = await ledger.verify_own(ctx.db, ctx.principal, project)
    await ctx.db.commit()
    return {"verified_entries": n}
