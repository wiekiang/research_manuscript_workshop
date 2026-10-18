from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..db.base import utcnow
from ..db.models.core import (
    BudgetAlert,
    BudgetChange,
    DataFlowAttestation,
    ModelInvocation,
    Notification,
    UsageLedgerEntry,
)
from ..deps import OWNER_ONLY, Ctx, project_for, user_ctx
from ..errors import not_found, unprocessable
from ..services import budget as budget_svc
from ..services.common import audit

router = APIRouter(tags=["costs"])


class CapIn(BaseModel):
    new_cap_cents: int = Field(ge=0, le=10_000_000)
    expected_version: int
    rationale: str = Field(min_length=3, max_length=2000)


class AttestIn(BaseModel):
    provider_key: str
    data_kinds: list[str] = Field(min_length=1)
    max_classification: str = Field(pattern="^(public|internal|restricted)$")
    attestation_accepted: bool


ATTESTATION_TEXT = (
    "I am the project owner. I have reviewed the data flow shown for this provider, including its recorded retention "
    "and training settings, and I have the rights and any coauthor or institutional authorizations needed to send the "
    "listed kinds of project data to it. Restricted human-subject or personal data is excluded unless a documented "
    "legal or contractual basis has been recorded."
)
DATA_KINDS = {"public_sources", "unpublished_manuscript", "coauthor_contributions", "uploaded_papers",
              "confidential_datasets", "cfp_documents"}


@router.get("/projects/{project_id}/usage")
async def usage(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, allow_admin_read=True)
    st = await budget_svc.status(ctx.db, project)
    by_cat = (await ctx.db.execute(select(
        UsageLedgerEntry.category, UsageLedgerEntry.provider, UsageLedgerEntry.billing_source,
        func.sum(UsageLedgerEntry.units), func.sum(UsageLedgerEntry.actual_cost_cents),
        func.sum(UsageLedgerEntry.estimated_cost_cents), func.count()).where(UsageLedgerEntry.project_id == project_id)
        .group_by(UsageLedgerEntry.category, UsageLedgerEntry.provider, UsageLedgerEntry.billing_source))).all()
    recent = (await ctx.db.execute(select(UsageLedgerEntry).where(UsageLedgerEntry.project_id == project_id)
                                   .order_by(UsageLedgerEntry.occurred_at.desc()).limit(50))).scalars()
    alerts = (await ctx.db.execute(select(BudgetAlert).where(BudgetAlert.project_id == project_id)
                                   .order_by(BudgetAlert.created_at))).scalars()
    invocations = (await ctx.db.execute(select(ModelInvocation).where(ModelInvocation.project_id == project_id)
                                        .order_by(ModelInvocation.created_at.desc()).limit(50))).scalars()
    changes = (await ctx.db.execute(select(BudgetChange).where(BudgetChange.project_id == project_id)
                                    .order_by(BudgetChange.created_at))).scalars()
    return {
        "budget": st.as_dict(),
        "stage_limits": project.stage_budget_limits,
        "by_category": [{"category": c, "provider": p, "billing_source": b, "units": float(u or 0),
                         "actual_cost_cents": int(a or 0), "estimated_cost_cents": int(e or 0), "entries": n}
                        for c, p, b, u, a, e, n in by_cat],
        "recent": [{"id": str(r.id), "category": r.category, "provider": r.provider, "units": float(r.units), "unit": r.unit,
                    "actual_cost_cents": r.actual_cost_cents, "estimated_cost_cents": r.estimated_cost_cents,
                    "billing_source": r.billing_source, "stage": r.stage, "occurred_at": r.occurred_at,
                    "unit_price_snapshot": r.unit_price_snapshot} for r in recent],
        "model_invocations": [{"id": str(m.id), "agent": m.agent, "provider": m.provider, "model": m.model,
                               "prompt_version": m.prompt_version, "status": m.status, "input_tokens": m.input_tokens,
                               "output_tokens": m.output_tokens, "estimated_cost_cents": m.estimated_cost_cents,
                               "actual_cost_cents": m.actual_cost_cents, "data_classification": m.data_classification,
                               "denial_reason": m.denial_reason, "created_at": m.created_at} for m in invocations],
        "alerts": [{"threshold_pct": a.threshold_pct, "cap_cents": a.cap_cents, "spent_cents": a.spent_cents,
                    "at": a.created_at} for a in alerts],
        "cap_changes": [{"previous_cap_cents": c.previous_cap_cents, "new_cap_cents": c.new_cap_cents,
                         "rationale": c.rationale, "at": c.created_at} for c in changes],
        "note": "Costs show the platform's recorded estimates and actuals. Researcher-connected provider usage is shown "
                "separately where the provider reports it. Prices are snapshots, not quotes.",
    }


@router.post("/projects/{project_id}/budget")
async def change_cap(project_id: uuid.UUID, body: CapIn, ctx: Ctx = Depends(user_ctx)):
    """Explicit human decision to change the cost ceiling (never automatic)."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    if project.version != body.expected_version:
        from ..errors import conflict

        raise conflict("stale_version", "project changed; reload and retry")
    ctx.db.add(BudgetChange(tenant_id=ctx.tenant_id, project_id=project_id, previous_cap_cents=project.budget_cap_cents,
                            new_cap_cents=body.new_cap_cents, actor_id=ctx.principal.user_id, rationale=body.rationale))
    await audit(ctx.db, ctx.principal, "budget.cap_changed", project_id=project_id,
                details={"from": project.budget_cap_cents, "to": body.new_cap_cents})
    project.budget_cap_cents = body.new_cap_cents
    project.version += 1
    await ctx.db.commit()
    return (await budget_svc.status(ctx.db, project)).as_dict()


@router.get("/projects/{project_id}/data-flow")
async def data_flow(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(DataFlowAttestation).where(DataFlowAttestation.project_id == project_id)
                                 .order_by(DataFlowAttestation.created_at.desc()))).scalars()
    return {"attestation_text": ATTESTATION_TEXT, "data_kinds": sorted(DATA_KINDS),
            "items": [{"id": str(a.id), "provider_key": a.provider_key, "data_kinds": a.data_kinds,
                       "max_classification": a.max_classification, "attested_at": a.created_at,
                       "revoked_at": a.revoked_at} for a in rows]}


@router.post("/projects/{project_id}/data-flow", status_code=201)
async def attest(project_id: uuid.UUID, body: AttestIn, ctx: Ctx = Depends(user_ctx)):
    """Project-owner attestation that project data may flow to a model/provider (§8)."""
    await project_for(ctx, project_id, OWNER_ONLY)
    if not body.attestation_accepted:
        raise unprocessable("attestation_required", "accept the data-flow attestation", {"text": ATTESTATION_TEXT})
    unknown = set(body.data_kinds) - DATA_KINDS
    if unknown:
        raise unprocessable("unknown_data_kind", f"unknown data kinds: {sorted(unknown)}")
    a = DataFlowAttestation(tenant_id=ctx.tenant_id, project_id=project_id, user_id=ctx.principal.user_id,
                            provider_key=body.provider_key, data_kinds=sorted(body.data_kinds),
                            max_classification=body.max_classification, attestation_text=ATTESTATION_TEXT)
    ctx.db.add(a)
    await audit(ctx.db, ctx.principal, "dataflow.attested", project_id=project_id,
                details={"provider": body.provider_key, "data_kinds": body.data_kinds})
    await ctx.db.commit()
    return {"id": str(a.id)}


@router.delete("/projects/{project_id}/data-flow/{attestation_id}", status_code=200)
async def revoke(project_id: uuid.UUID, attestation_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, OWNER_ONLY)
    a = (await ctx.db.execute(select(DataFlowAttestation).where(DataFlowAttestation.id == attestation_id,
                                                                DataFlowAttestation.project_id == project_id))).scalar_one_or_none()
    if a is None:
        raise not_found("attestation")
    a.revoked_at = utcnow()
    await audit(ctx.db, ctx.principal, "dataflow.revoked", project_id=project_id, details={"provider": a.provider_key})
    await ctx.db.commit()
    return {"revoked": True}


@router.get("/notifications")
async def notifications(ctx: Ctx = Depends(user_ctx), unread_only: bool = False):
    q = select(Notification).where(Notification.user_id == ctx.principal.user_id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = (await ctx.db.execute(q.order_by(Notification.created_at.desc()).limit(100))).scalars()
    return {"items": [{"id": str(n.id), "type": n.type, "title": n.title, "body": n.body, "link": n.link,
                       "project_id": str(n.project_id) if n.project_id else None, "read_at": n.read_at,
                       "created_at": n.created_at} for n in rows]}


@router.post("/notifications/read-all")
async def mark_all_read(ctx: Ctx = Depends(user_ctx)):
    rows = list((await ctx.db.execute(select(Notification).where(Notification.user_id == ctx.principal.user_id,
                                                                 Notification.read_at.is_(None)))).scalars())
    now = utcnow()
    for n in rows:
        n.read_at = now
    await ctx.db.commit()
    return {"read": len(rows)}


@router.post("/notifications/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    n = (await ctx.db.execute(select(Notification).where(Notification.id == notification_id,
                                                         Notification.user_id == ctx.principal.user_id))).scalar_one_or_none()
    if n is None:
        raise not_found("notification")
    n.read_at = utcnow()
    await ctx.db.commit()
    return {"read": True}
