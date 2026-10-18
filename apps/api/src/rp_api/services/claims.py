"""Claim registry and policy-based verification (PRODUCT_SPEC §2.6).

Only this service sets a claim's status. It gathers the recorded checks for the claim, evaluates the active
immutable verification policy, appends a ClaimDecision (old decisions are retained) and sets gate eligibility.
A decision made under a superseded policy can satisfy a current gate only after re-evaluation under the
current policy; a stricter human-review rule can never be satisfied by a model-only history.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import CRITICAL_CLAIM_CATEGORIES, ClaimCategory
from rp_contracts.verification import POLICY_V1, Evidence, VerificationPolicy, evaluate

from ..db.engine import session_scope
from ..db.models.literature import (
    Claim,
    ClaimDecision,
    ClaimSupport,
    EvidencePassage,
    TenantPaperRecord,
    VerificationPolicyRecord,
    VerificationRecord,
)
from ..security.tokens import Principal
from .common import audit

CATEGORIES = {c.value for c in ClaimCategory}


async def active_policy(db: AsyncSession | None = None) -> VerificationPolicy:
    async def _load(s):
        row = (await s.execute(select(VerificationPolicyRecord).where(VerificationPolicyRecord.active.is_(True))
                               .order_by(VerificationPolicyRecord.created_at.desc()))).scalars().first()
        return VerificationPolicy.model_validate(row.rules) if row else POLICY_V1

    if db is not None:
        return await _load(db)
    async with session_scope("app") as s:
        return await _load(s)


async def next_claim_key(db: AsyncSession, project_id: uuid.UUID) -> str:
    n = (await db.execute(select(func.count()).select_from(Claim).where(Claim.project_id == project_id))).scalar_one()
    return f"CLM-{n + 1:04d}"


async def gather(db: AsyncSession, claim: Claim) -> Evidence:
    supports = list((await db.execute(select(ClaimSupport).where(ClaimSupport.claim_id == claim.id,
                                                                 ClaimSupport.is_current.is_(True)))).scalars())
    records = list((await db.execute(select(VerificationRecord).where(VerificationRecord.claim_id == claim.id,
                                                                      VerificationRecord.is_current.is_(True)))).scalars())
    ev = Evidence()
    support_rel = [s for s in supports if s.relation in ("supports", "qualifies")]
    paper_ids = {s.paper_id for s in support_rel if s.paper_id}
    passages = {}
    pids = [s.passage_id for s in support_rel if s.passage_id]
    if pids:
        passages = {p.id: p for p in (await db.execute(select(EvidencePassage).where(EvidencePassage.id.in_(pids)))).scalars()}
        paper_ids |= {p.paper_id for p in passages.values()}
    papers = {p.id: p for p in (await db.execute(select(TenantPaperRecord).where(TenantPaperRecord.id.in_(paper_ids)))).scalars()} if paper_ids else {}
    ev.identity_all_verified = bool(papers) and all(p.identity_status == "verified" for p in papers.values())
    verified_passages = [p for p in passages.values() if p.verified_in_source and p.freshness == "current"]
    ev.has_verified_passage = bool(verified_passages)
    ev.passage_from_fulltext = any(p.source_kind == "fulltext" for p in verified_passages)
    ev.has_result_or_table = any(s.result_ref for s in support_rel) or any(p.role in ("result", "table") for p in verified_passages)
    for r in records:
        if r.check == "support" and r.outcome in ("supports",):
            if r.method == "human":
                ev.human_support = True
            elif r.method == "model_assisted":
                ev.model_support = True
        if r.check == "support" and r.outcome == "contradicts":
            ev.contradiction_unresolved = True
        if r.check == "strength" and r.outcome == "mismatch":
            ev.strength_mismatch = True
        if r.check == "strength" and r.outcome == "resolved_by_human":
            ev.strength_mismatch = False
        if r.check == "units" and r.outcome == "recorded":
            ev.units_recorded = True
        if r.check == "closest_work" and r.outcome == "assessed":
            ev.closest_work_assessed = True
        if r.check == "human_judgment" and r.outcome == "recorded" and r.method == "human":
            ev.human_judgment = True
        if r.check == "authoritative_source" and r.outcome == "recorded":
            ev.authoritative_source = True
        if r.check == "contradiction" and r.outcome == "resolved" and r.method == "human":
            ev.contradiction_unresolved = False
    if any(s.relation == "contradicts" for s in supports):
        ev.contradiction_unresolved = ev.contradiction_unresolved or not any(
            r.check == "contradiction" and r.outcome == "resolved" and r.method == "human" for r in records)
    return ev


async def reevaluate(db: AsyncSession, actor: Principal | None, claim: Claim, study_type: str | None = None) -> ClaimDecision:
    policy = await active_policy(db)
    ev = await gather(db, claim)
    d = evaluate(policy, claim.category, ev, study_type)
    for old in (await db.execute(select(ClaimDecision).where(ClaimDecision.claim_id == claim.id,
                                                             ClaimDecision.state.in_(["current", "needs_reassessment"])))).scalars():
        old.state = "superseded"
    rec = ClaimDecision(tenant_id=claim.tenant_id, claim_id=claim.id, policy_version=d.policy_version, rule_id=d.rule_id,
                        status=d.status, satisfied=d.satisfied, outstanding=d.outstanding, human_required=d.human_required,
                        state="current", evidence_snapshot=ev.__dict__.copy(),
                        decided_by=actor.actor_id if actor else "system")
    db.add(rec)
    claim.status = "verified" if d.status == "verified" else ("contested" if ev.contradiction_unresolved else "unverified")
    claim.gate_eligible = d.status == "verified"
    claim.decision = d.as_dict()
    claim.version += 1
    await db.flush()
    if actor is not None:
        await audit(db, actor, "claim.evaluated", project_id=claim.project_id, resource_type="claim", resource_id=claim.id,
                    details={"policy": d.policy_version, "status": d.status, "outstanding": d.outstanding})
    return rec


async def gate_eligible(db: AsyncSession, claim: Claim) -> bool:
    """Gate-time check: the latest decision must be verified under the *active* policy version."""
    policy = await active_policy(db)
    dec = (await db.execute(select(ClaimDecision).where(ClaimDecision.claim_id == claim.id, ClaimDecision.state == "current")
                            .order_by(ClaimDecision.created_at.desc()))).scalars().first()
    return bool(dec and dec.status == "verified" and dec.policy_version == policy.version)


def is_critical(category: str) -> bool:
    return category in {c.value for c in CRITICAL_CLAIM_CATEGORIES}


async def publish_policy(policy: VerificationPolicy, operator: str) -> dict:
    """Publish a new immutable policy; mark every decision made under another version as needs_reassessment."""
    async with session_scope("ingest") as idb:
        if (await idb.execute(select(VerificationPolicyRecord).where(VerificationPolicyRecord.version == policy.version))).scalar_one_or_none():
            raise ValueError(f"policy {policy.version} already exists; published policies are immutable")
        prev = (await idb.execute(select(VerificationPolicyRecord).where(VerificationPolicyRecord.active.is_(True)))).scalars().all()
        for p in prev:
            p.active = False
        idb.add(VerificationPolicyRecord(version=policy.version, rules=policy.model_dump(), active=True,
                                         published_by=operator, supersedes=prev[0].version if prev else None))
        await idb.commit()
    async with session_scope("system") as sdb:
        res = await sdb.execute(update(ClaimDecision).where(ClaimDecision.state == "current",
                                                            ClaimDecision.policy_version != policy.version)
                                .values(state="needs_reassessment"))
        await sdb.execute(update(Claim).where(Claim.gate_eligible.is_(True)).values(gate_eligible=False))
        await sdb.commit()
    return {"version": policy.version, "decisions_marked_needs_reassessment": res.rowcount}


async def reassess_project(db: AsyncSession, actor: Principal | None, project_id: uuid.UUID) -> dict:
    """Re-evaluate claims whose decision predates the active policy. A decision is preserved only when its recorded
    evidence satisfies the new rule (the comparison is stored); otherwise the claim stays unverified."""
    policy = await active_policy(db)
    claims = list((await db.execute(select(Claim).where(Claim.project_id == project_id, Claim.superseded_by.is_(None)))).scalars())
    kept = reopened = 0
    for c in claims:
        dec = (await db.execute(select(ClaimDecision).where(ClaimDecision.claim_id == c.id)
                                .order_by(ClaimDecision.created_at.desc()))).scalars().first()
        if dec is None or (dec.policy_version == policy.version and dec.state == "current"):
            continue
        was_verified = dec.status == "verified"
        new = await reevaluate(db, actor, c)
        new.migrated_from = dec.id
        if was_verified and new.status == "verified":
            new.state = "current"
            kept += 1
        elif was_verified:
            reopened += 1
    return {"policy": policy.version, "kept_with_proof": kept, "reopened": reopened}


_ = CATEGORIES
