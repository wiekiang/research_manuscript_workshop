"""M7 - independent review functions, meta-review, finding resolution, compliance and research-integrity reports."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import LedgerCategory, ProjectState
from rp_contracts.hashing import canonical_json, content_hash, sha256_hex
from rp_contracts.integrity import ENGINE_VERSION, IntegrityCheck, summarize
from rp_contracts.manuscript import ManuscriptContent, section_text, word_count
from rp_contracts.review import (
    FUNCTIONS,
    MAX_REVISION_CYCLES,
    SAMPLING_RULE,
    SCIENTIFIC_GATE_FUNCTIONS,
    ComplianceCheck,
    Finding,
)

from ..db.base import utcnow
from ..db.models.cfp import CfpRule, SourceSnapshot
from ..db.models.contribution import Contribution, Protocol, ResultAssessmentRecord, ResultManifestRecord
from ..db.models.core import Artifact, Project, ProjectMember, User
from ..db.models.latex import CompileRun
from ..db.models.literature import Claim, ClaimSupport, EvidencePassage, TenantPaperRecord
from ..db.models.manuscript import BibliographyEntry, Manuscript, ManuscriptSpan, ManuscriptVersion
from ..db.models.review import (
    CheckDecision,
    ClaimCheckRecord,
    IntegrityReport,
    ReviewFinding,
    ReviewReport,
    ReviewRevision,
    ReviewRound,
)
from ..deps import EDIT_ROLES, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import artifacts as art_svc
from ..services import ledger
from ..services.common import audit
from ..services.gates import GateResult, gate
from ..services.tasks import create_task
from .manuscript import check_context, current_content, start_generation
from .method import active_instance, frozen_protocol

router = APIRouter(tags=["review"])
REVIEWABLE = {ProjectState.SCIENTIFIC_REVIEW, ProjectState.COMPLIANCE_REVIEW, ProjectState.FINAL_APPROVAL}
DECISION_DECLARATION = ("I reviewed this check, its evidence and its limitations, and I take responsibility for this "
                        "decision. It is recorded with my name and cannot be changed.")
MUST_FIX = {"source_not_performed", "source_failed", "unsupported", "contradicted"}


# --------------------------------------------------------------------------- helpers
async def current_version(db: AsyncSession, project_id: uuid.UUID) -> tuple[Manuscript, ManuscriptVersion, ManuscriptContent]:
    m = (await db.execute(select(Manuscript).where(Manuscript.project_id == project_id))).scalar_one_or_none()
    if m is None or m.current_version_id is None:
        raise unprocessable("no_manuscript", "draft the manuscript first")
    v, content = await current_content(db, m)
    return m, v, content


def content_digest(content: ManuscriptContent) -> str:
    return sha256_hex(canonical_json(content.model_dump(mode="json")))


async def latest_round(db: AsyncSession, project_id: uuid.UUID, version_id: uuid.UUID, function: str) -> ReviewRound | None:
    rows = (await db.execute(select(ReviewRound).where(ReviewRound.project_id == project_id,
                                                       ReviewRound.manuscript_version_id == version_id,
                                                       ReviewRound.status == "complete")
                             .order_by(ReviewRound.created_at.desc()))).scalars()
    return next((r for r in rows if function in r.functions), None)


async def manuscript_compile_run(db: AsyncSession, project_id: uuid.UUID, version_id: uuid.UUID) -> CompileRun | None:
    return (await db.execute(select(CompileRun).where(CompileRun.project_id == project_id, CompileRun.kind == "manuscript",
                                                      CompileRun.manuscript_version_id == version_id)
                             .order_by(CompileRun.created_at.desc()))).scalars().first()


def finding_out(f: ReviewFinding) -> dict:
    return {"id": str(f.id), "function": f.function, "severity": f.severity, "category": f.category, "title": f.title,
            "rationale": f.rationale, "check": f.check, "proposed_fix": f.proposed_fix, "span_ids": f.span_ids,
            "claim_ids": f.claim_ids, "artifact_ids": f.artifact_ids, "rule_ids": f.rule_ids, "status": f.status,
            "resolution_note": f.resolution_note, "resolved_by": str(f.resolved_by) if f.resolved_by else None,
            "resolved_at": f.resolved_at, "resolved_in_version": f.resolved_in_version}


async def round_out(db: AsyncSession, r: ReviewRound, detail: bool = True) -> dict:
    reports = list((await db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id))).scalars())
    out = {"id": str(r.id), "manuscript_version": r.manuscript_version_number, "manuscript_version_id": str(r.manuscript_version_id),
           "status": r.status, "functions": r.functions, "task_id": str(r.task_id), "created_at": r.created_at,
           "meta": r.meta, "meta_artifact_id": str(r.meta_artifact_id) if r.meta_artifact_id else None,
           "reports": [{"function": x.function, "status": x.status, "artifact_id": str(x.artifact_id), "frozen_at": x.frozen_at,
                        "summary": x.summary, "provenance": x.provenance} for x in reports]}
    if detail:
        fs = (await db.execute(select(ReviewFinding).where(ReviewFinding.round_id == r.id)
                               .order_by(ReviewFinding.created_at))).scalars()
        out["findings"] = [finding_out(f) for f in fs]
        cc = (await db.execute(select(ClaimCheckRecord).where(ClaimCheckRecord.round_id == r.id)
                               .order_by(ClaimCheckRecord.claim_key))).scalars()
        out["claim_checks"] = [{"claim_key": c.claim_key, "critical": c.critical, "selection": c.selection,
                                "source_status": c.source_status, "source_detail": c.source_detail, "meaning": c.meaning,
                                "method": c.method, "reused": c.reused_from is not None} for c in cc]
        compliance = next((x for x in reports if x.function == "compliance"), None)
        if compliance:
            decs = (await db.execute(select(CheckDecision).where(CheckDecision.scope == "compliance",
                                                                 CheckDecision.report_id == compliance.id))).scalars()
            out["compliance_decisions"] = [{"check_id": d.check_id, "decision": d.decision, "rationale": d.rationale,
                                            "decided_by": str(d.decided_by), "at": d.created_at} for d in decs]
    return out


# --------------------------------------------------------------------------- user endpoints
class ReviewIn(BaseModel):
    functions: list[str] | None = None


@router.post("/projects/{project_id}/reviews", status_code=202)
async def request_review(project_id: uuid.UUID, body: ReviewIn, ctx: Ctx = Depends(user_ctx),
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    if ProjectState(project.state) not in REVIEWABLE:
        raise conflict("wrong_state", f"independent review runs once the manuscript is complete (project is {project.state})")
    m, v, _ = await current_version(ctx.db, project_id)
    fns = [f for f in (body.functions or list(FUNCTIONS)) if f in FUNCTIONS]
    if not fns:
        raise unprocessable("unknown_functions", f"functions must be among {list(FUNCTIONS)}")
    round_id = uuid.uuid4()
    task, created = await create_task(ctx.db, ctx.principal, project, "review_run", {"functions": fns, "round_id": str(round_id)},
                                      idempotency_key=f"review:{project_id}:{idempotency_key}" if idempotency_key else None,
                                      input_manifest={"version": str(v.id), "hash": v.content_hash, "functions": fns,
                                                      "nonce": idempotency_key})
    if created:
        ctx.db.add(ReviewRound(id=round_id, tenant_id=ctx.tenant_id, project_id=project_id, manuscript_id=m.id,
                               manuscript_version_id=v.id, manuscript_version_number=v.version_number, task_id=task.id,
                               functions=fns, requested_by=ctx.principal.actor_id))
    await ctx.db.commit()
    return {"task": task_out(task), "manuscript_version": v.version_number}


@router.get("/projects/{project_id}/reviews")
async def list_reviews(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rounds = list((await ctx.db.execute(select(ReviewRound).where(ReviewRound.project_id == project_id)
                                        .order_by(ReviewRound.created_at.desc()))).scalars())
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.project_id == project_id))).scalar_one_or_none()
    used = (await ctx.db.execute(select(func.count()).select_from(ReviewRevision).where(
        ReviewRevision.manuscript_id == m.id))).scalar_one() if m else 0
    return {"items": [await round_out(ctx.db, r, detail=i == 0) for i, r in enumerate(rounds)],
            "current_version_id": str(m.current_version_id) if m and m.current_version_id else None,
            "revision_cycles": {"used": used, "limit": MAX_REVISION_CYCLES}, "sampling_rule": SAMPLING_RULE,
            "decision_declaration": DECISION_DECLARATION}


async def _round(ctx: Ctx, round_id: uuid.UUID) -> ReviewRound:
    r = (await ctx.db.execute(select(ReviewRound).where(ReviewRound.id == round_id))).scalar_one_or_none()
    if r is None:
        raise not_found("review")
    return r


@router.get("/reviews/{round_id}")
async def get_review(round_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    r = await _round(ctx, round_id)
    await project_for(ctx, r.project_id)
    return await round_out(ctx.db, r)


class ResolveIn(BaseModel):
    resolution: str = Field(pattern="^(fixed|accepted_risk|rejected_with_reason)$")
    note: str = Field(min_length=1, max_length=4000)


@router.post("/review-findings/{finding_id}/resolve")
async def resolve_finding(finding_id: uuid.UUID, body: ResolveIn, ctx: Ctx = Depends(user_ctx)):
    """Only a human researcher resolves findings. Blockers cannot be accepted as risks; missing or contradicting
    evidence must be fixed. 'fixed' requires a newer committed version, which the next review round re-checks."""
    f = (await ctx.db.execute(select(ReviewFinding).where(ReviewFinding.id == finding_id).with_for_update())).scalar_one_or_none()
    if f is None:
        raise not_found("finding")
    project, _ = await project_for(ctx, f.project_id, EDIT_ROLES)
    if f.status != "open":
        raise conflict("already_resolved", f"finding is {f.status}")
    rnd = await _round(ctx, f.round_id)
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.id == rnd.manuscript_id))).scalar_one()
    if body.resolution == "fixed" and m.current_version_number <= rnd.manuscript_version_number:
        raise conflict("no_newer_version", "edit the manuscript first; the fix is checked by the next review round")
    if body.resolution != "fixed":
        if len(body.note.strip()) < 20:
            raise unprocessable("rationale_required", "explain the decision in your own words (at least 20 characters)")
        if f.severity == "blocker" and body.resolution == "accepted_risk":
            raise unprocessable("blocker_cannot_be_accepted", "a blocker must be fixed or rejected with a reason")
        if f.category in MUST_FIX:
            raise unprocessable("must_fix", "missing, failed or contradicting evidence must be fixed, not waived")
    f.status, f.resolution_note, f.resolved_by, f.resolved_at = body.resolution, body.note, ctx.principal.user_id, utcnow()
    f.resolved_in_version = m.current_version_number
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION,
                         f"Resolved {f.severity} review finding ({body.resolution}): {f.title}"[:2000],
                         source_action="review.resolve", rationale=body.note, rationale_requested=False,
                         source_ref=str(f.id))
    await ctx.db.commit()
    return finding_out(f)


class ReviseIn(BaseModel):
    finding_ids: list[uuid.UUID] | None = None


@router.post("/reviews/{round_id}/revise", status_code=202)
async def revise(round_id: uuid.UUID, body: ReviseIn, ctx: Ctx = Depends(user_ctx)):
    """Automatic revision is limited to two cycles; the result is a candidate the researcher must apply or merge."""
    r = await _round(ctx, round_id)
    project, _ = await project_for(ctx, r.project_id, EDIT_ROLES, lock=True)
    if r.status != "complete":
        raise conflict("review_incomplete", "wait for the review round to finish")
    used = (await ctx.db.execute(select(func.count()).select_from(ReviewRevision).where(
        ReviewRevision.manuscript_id == r.manuscript_id))).scalar_one()
    if used >= MAX_REVISION_CYCLES:
        raise conflict("revision_limit_reached", f"automatic revision is limited to {MAX_REVISION_CYCLES} cycles; resolve the "
                                                 "remaining findings yourself", {"used": used})
    q = select(ReviewFinding).where(ReviewFinding.round_id == r.id, ReviewFinding.status == "open")
    fs = [f for f in (await ctx.db.execute(q)).scalars()
          if (body.finding_ids is None and f.severity in ("blocker", "major")) or (body.finding_ids and f.id in body.finding_ids)]
    span_ids = {s for f in fs for s in f.span_ids}
    sections = sorted({s.section_key for s in (await ctx.db.execute(select(ManuscriptSpan).where(
        ManuscriptSpan.version_id == r.manuscript_version_id, ManuscriptSpan.span_id.in_(span_ids)))).scalars()}) if span_ids else []
    if not sections:
        raise unprocessable("nothing_to_revise", "no open finding points at manuscript text")
    instructions = "Revise to address these independent review findings:\n" + "\n".join(
        f"- [{f.severity}] {f.title}: {f.rationale}" + (f" Proposed fix: {f.proposed_fix}" if f.proposed_fix else "")
        for f in fs if set(f.span_ids) & span_ids)
    g = await start_generation(ctx.db, ctx.principal, project, sections, instructions[:4000], f"revise:{r.id}:{used + 1}")
    ctx.db.add(ReviewRevision(tenant_id=ctx.tenant_id, manuscript_id=r.manuscript_id, round_id=r.id, cycle=used + 1,
                              task_id=g["task"].id, finding_ids=[str(f.id) for f in fs], sections=sections))
    await ctx.db.commit()
    return {"task": task_out(g["task"]), "cycle": used + 1, "remaining": MAX_REVISION_CYCLES - used - 1, "sections": sections}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(accepted_risk|resolved|not_applicable)$")
    rationale: str = Field(min_length=20, max_length=4000)
    declaration_accepted: bool
    declaration_text: str


async def _record_decision(ctx: Ctx, project: Project, scope: str, report_id: uuid.UUID, check_id: str, body: DecisionIn,
                           role: str) -> CheckDecision:
    if not body.declaration_accepted or body.declaration_text != DECISION_DECLARATION:
        raise unprocessable("declaration_mismatch", "accept the exact declaration text", {"declaration": DECISION_DECLARATION})
    d = CheckDecision(tenant_id=ctx.tenant_id, project_id=project.id, scope=scope, report_id=report_id, check_id=check_id,
                      decision=body.decision, rationale=body.rationale, declaration_text=body.declaration_text,
                      decided_by=ctx.principal.user_id, decided_role=role)
    ctx.db.add(d)
    await audit(ctx.db, ctx.principal, f"{scope}.check_decided", tenant_id=ctx.tenant_id, project_id=project.id,
                resource_type=f"{scope}_check", details={"check_id": check_id, "decision": body.decision})
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.OTHER,
                         f"Signed {scope} decision on {check_id}: {body.decision}", source_action=f"{scope}.decide",
                         rationale=body.rationale, rationale_requested=False)
    return d


@router.post("/reviews/{round_id}/compliance/{check_id}/decide", status_code=201)
async def decide_compliance(round_id: uuid.UUID, check_id: str, body: DecisionIn, ctx: Ctx = Depends(user_ctx)):
    r = await _round(ctx, round_id)
    project, role = await project_for(ctx, r.project_id, EDIT_ROLES)
    rep = (await ctx.db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id,
                                                           ReviewReport.function == "compliance"))).scalar_one_or_none()
    if rep is None:
        raise not_found("compliance report")
    chk = next((c for c in rep.summary.get("checks", []) if c["id"] == check_id), None)
    if chk is None:
        raise not_found("check")
    if chk["status"] != "manual_check":
        raise conflict("not_manual", f"only manual checks take a signed decision (this check is {chk['status']})")
    d = await _record_decision(ctx, project, "compliance", rep.id, check_id, body, role)
    await ctx.db.commit()
    return {"id": str(d.id), "check_id": check_id, "decision": d.decision}


# --------------------------------------------------------------------------- integrity endpoints
@router.post("/projects/{project_id}/integrity", status_code=202)
async def request_integrity(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    if ProjectState(project.state) not in REVIEWABLE:
        raise conflict("wrong_state", f"integrity checks run on a complete manuscript (project is {project.state})")
    _, v, _ = await current_version(ctx.db, project_id)
    nonce = (await ctx.db.execute(select(func.count()).select_from(IntegrityReport).where(
        IntegrityReport.project_id == project_id))).scalar_one()
    report_id = uuid.uuid4()
    task, created = await create_task(ctx.db, ctx.principal, project, "integrity_check", {"report_id": str(report_id)},
                                      input_manifest={"version": str(v.id), "n": nonce})
    if created:
        ctx.db.add(IntegrityReport(id=report_id, tenant_id=ctx.tenant_id, project_id=project_id, manuscript_version_id=v.id,
                                   task_id=task.id, engine_version=ENGINE_VERSION))
    await ctx.db.commit()
    return {"task": task_out(task)}


async def integrity_out(db: AsyncSession, rep: IntegrityReport) -> dict:
    decs = {d.check_id: d for d in (await db.execute(select(CheckDecision).where(
        CheckDecision.scope == "integrity", CheckDecision.report_id == rep.id))).scalars()}
    checks = [IntegrityCheck.model_validate(c) for c in rep.checks]
    summary = summarize(checks, {k: {} for k in decs})
    v = (await db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == rep.manuscript_version_id))).scalar_one()
    return {"id": str(rep.id), "status": rep.status, "manuscript_version": v.version_number, "engine": rep.engine_version,
            "artifact_id": str(rep.artifact_id) if rep.artifact_id else None, "created_at": rep.created_at,
            "checks": [{**c.model_dump(), "requires_decision": c.requires_decision,
                        "decision": ({"decision": decs[c.id].decision, "rationale": decs[c.id].rationale,
                                      "decided_by": str(decs[c.id].decided_by), "at": decs[c.id].created_at}
                                     if c.id in decs else None)} for c in checks],
            "summary": summary}


@router.get("/projects/{project_id}/integrity")
async def get_integrity(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    reps = list((await ctx.db.execute(select(IntegrityReport).where(IntegrityReport.project_id == project_id)
                                      .order_by(IntegrityReport.created_at.desc()))).scalars())
    return {"items": [await integrity_out(ctx.db, r) for r in reps[:5]], "decision_declaration": DECISION_DECLARATION}


@router.post("/integrity-reports/{report_id}/checks/{check_id}/decide", status_code=201)
async def decide_integrity(report_id: uuid.UUID, check_id: str, body: DecisionIn, ctx: Ctx = Depends(user_ctx)):
    rep = (await ctx.db.execute(select(IntegrityReport).where(IntegrityReport.id == report_id))).scalar_one_or_none()
    if rep is None:
        raise not_found("integrity report")
    project, role = await project_for(ctx, rep.project_id, EDIT_ROLES)
    chk = next((c for c in rep.checks if c["id"] == check_id), None)
    if chk is None:
        raise not_found("check")
    if chk["status"] not in ("warning", "manual_check"):
        raise conflict("not_decidable", f"a {chk['status']} check cannot be waived; fix the underlying problem and re-run")
    d = await _record_decision(ctx, project, "integrity", rep.id, check_id, body, role)
    await ctx.db.commit()
    return {"id": str(d.id), "check_id": check_id, "decision": d.decision}


# --------------------------------------------------------------------------- gates
@gate("review.passed")
async def review_passed(db: AsyncSession, project: Project) -> GateResult:
    try:
        _, v, _ = await current_version(db, project.id)
    except ApiError:
        return GateResult("review.passed", False, ["no manuscript"])
    reasons: list[str] = []
    rounds = {f: await latest_round(db, project.id, v.id, f) for f in SCIENTIFIC_GATE_FUNCTIONS}
    missing = [f for f, r in rounds.items() if r is None]
    if missing:
        return GateResult("review.passed", False, [f"run the independent review ({', '.join(missing)}) on the current "
                                                   f"manuscript version v{v.version_number}"], next_action="Run review")
    for f, r in rounds.items():
        rep = (await db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id, ReviewReport.function == f))).scalar_one()
        if rep.status == "not_performed":
            reasons.append(f"the {f} review was not performed: {rep.summary.get('reason')}")
        if r.meta is None:
            reasons.append("the meta-review has not consolidated the frozen reports")
        open_ = (await db.execute(select(func.count()).select_from(ReviewFinding).where(
            ReviewFinding.round_id == r.id, ReviewFinding.function == f, ReviewFinding.status == "open",
            ReviewFinding.severity.in_(["blocker", "major"])))).scalar_one()
        if open_:
            reasons.append(f"{open_} open blocker/major {f} finding(s)")
    return GateResult("review.passed", not reasons, sorted(set(reasons)), evidence={"version": v.version_number},
                      next_action="Resolve review findings" if reasons else None)


@gate("compliance.checked")
async def compliance_checked(db: AsyncSession, project: Project) -> GateResult:
    try:
        _, v, _ = await current_version(db, project.id)
    except ApiError:
        return GateResult("compliance.checked", False, ["no manuscript"])
    r = await latest_round(db, project.id, v.id, "compliance")
    if r is None:
        return GateResult("compliance.checked", False, [f"run the venue-compliance review on v{v.version_number}"])
    rep = (await db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id,
                                                       ReviewReport.function == "compliance"))).scalar_one()
    art = (await db.execute(select(Artifact).where(Artifact.id == rep.artifact_id))).scalar_one()
    reasons = []
    if art.freshness != "current":
        reasons.append(f"the compliance report is stale ({art.stale_reason}); re-run it")
    decided = set((await db.execute(select(CheckDecision.check_id).where(CheckDecision.scope == "compliance",
                                                                         CheckDecision.report_id == rep.id))).scalars())
    for c in rep.summary.get("checks", []):
        if c["status"] in ("failed", "not_performed") and c.get("blocking", True):
            reasons.append(f"{c['id']}: {c['status']} - {c['detail']}")
        elif c["status"] == "manual_check" and c.get("blocking", True) and c["id"] not in decided:
            reasons.append(f"{c['id']}: needs a signed human resolution - {c['detail']}")
    return GateResult("compliance.checked", not reasons, reasons, evidence={"version": v.version_number, "report": str(rep.id)})


@gate("integrity.checked")
async def integrity_checked(db: AsyncSession, project: Project) -> GateResult:
    try:
        _, v, _ = await current_version(db, project.id)
    except ApiError:
        return GateResult("integrity.checked", False, ["no manuscript"])
    rep = (await db.execute(select(IntegrityReport).where(IntegrityReport.project_id == project.id,
                                                          IntegrityReport.manuscript_version_id == v.id,
                                                          IntegrityReport.status == "complete")
                            .order_by(IntegrityReport.created_at.desc()))).scalars().first()
    if rep is None:
        return GateResult("integrity.checked", False, [f"run the integrity checks on v{v.version_number}"])
    out = await integrity_out(db, rep)
    reasons = [f"{c}: failed or not performed" for c in out["summary"]["failed"]] + \
              [f"{c}: needs a signed human decision" for c in out["summary"]["awaiting_decision"]]
    return GateResult("integrity.checked", not reasons, reasons, evidence={"report": str(rep.id)})


# --------------------------------------------------------------------------- internal: inputs per function (isolation)
async def _internal_round(ctx: Ctx, round_id: uuid.UUID) -> tuple[ReviewRound, Project]:
    require_task_kind(ctx, "review_run")
    r = (await ctx.db.execute(select(ReviewRound).where(ReviewRound.id == round_id))).scalar_one_or_none()
    if r is None:
        raise not_found("review")
    require_service_scope(ctx, r.project_id, "domain.read")
    project, _ = await project_for(ctx, r.project_id)
    return r, project


async def _version_payload(db, r: ReviewRound) -> tuple[ManuscriptContent, list[ManuscriptSpan], ManuscriptVersion]:
    v = (await db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == r.manuscript_version_id))).scalar_one()
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(db, v.artifact_id))
    spans = list((await db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == v.id)
                                   .order_by(ManuscriptSpan.position))).scalars())
    return ManuscriptContent.model_validate(data["content"]), spans, v


def _spans_json(spans: list[ManuscriptSpan]) -> list[dict]:
    return [{"span_id": s.span_id, "section": s.section_key, "kind": s.kind, "text": s.text, "claim_ids": s.claim_ids,
             "result_keys": s.result_keys, "origin": s.origin, "issues": s.issues} for s in spans]


async def _results(db, project_id) -> dict[str, dict]:
    inst = await active_instance(db, project_id)
    if inst is None:
        return {}
    out = {}
    for r in (await db.execute(select(ResultManifestRecord).where(ResultManifestRecord.method_instance_id == inst.id,
                                                                  ResultManifestRecord.is_current.is_(True)))).scalars():
        a = (await db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == r.id,
                                                                   ResultAssessmentRecord.is_current.is_(True)))).scalars().first()
        out[r.result_key] = {"result_id": str(r.id), "title": r.title, "manifest": r.manifest, "artifact_id": str(r.artifact_id),
                             "assurance": r.assurance_level, "wording_limits": a.wording_limits if a else [],
                             "assessment_blockers": a.blockers if a else ["not assessed"],
                             "assessment_checks": a.checks if a else []}
    return out


@router.get("/internal/reviews/{round_id}/inputs/{function}")
async def review_inputs(round_id: uuid.UUID, function: str, ctx: Ctx = Depends(service_ctx)):
    """Each function receives only its own inputs - never another function's report (Reviewer Independence Policy)."""
    r, project = await _internal_round(ctx, round_id)
    if function not in r.functions:
        raise not_found("function")
    content, spans, v = await _version_payload(ctx.db, r)
    base = {"round_id": str(r.id), "function": function, "manuscript_version": v.version_number,
            "manuscript_artifact_id": str(v.artifact_id), "content_digest": content_digest(content)}
    if function == "scientific":
        cc = await check_context(ctx.db, project)
        inst = await active_instance(ctx.db, project.id)
        fp = await frozen_protocol(ctx.db, inst.id) if inst else None
        matrix = (await ctx.db.execute(select(Artifact).where(Artifact.project_id == project.id, Artifact.kind == "contribution_matrix",
                                                              Artifact.freshness == "current")
                                       .order_by(Artifact.created_at.desc()))).scalars().first()
        return {**base, "manuscript": content.model_dump(mode="json"), "spans": _spans_json(spans),
                "protocol": {"version": fp.version_number, "hash": fp.content_hash, "sections": fp.sections} if fp else None,
                "matrix": await art_svc.read_artifact_json(matrix) if matrix else None,
                "claims": [{"key": k, **x} for k, x in sorted(cc["claims"].items())],
                "results": {k: {x: y for x, y in r_.items() if x in ("title", "assurance", "wording_limits")}
                            | {"metrics": r_["manifest"].get("metrics", [])} for k, r_ in (await _results(ctx.db, project.id)).items()}}
    if function == "citation_evidence":
        cited = sorted({c for s in spans for c in s.claim_ids})
        claims = {c.claim_key: c for c in (await ctx.db.execute(select(Claim).where(
            Claim.project_id == project.id, Claim.claim_key.in_(cited), Claim.superseded_by.is_(None)))).scalars()}
        results = await _results(ctx.db, project.id)
        items = []
        for key in cited:
            c = claims.get(key)
            if c is None:
                items.append({"key": key, "missing": True})
                continue
            sups = list((await ctx.db.execute(select(ClaimSupport).where(ClaimSupport.claim_id == c.id, ClaimSupport.is_current.is_(True),
                                                                         ClaimSupport.relation.in_(["supports", "qualifies"])))).scalars())
            evidence = []
            for s in sups:
                if s.passage_id:
                    p = (await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.id == s.passage_id))).scalar_one()
                    paper = (await ctx.db.execute(select(TenantPaperRecord).where(TenantPaperRecord.id == p.paper_id))).scalar_one()
                    evidence.append({"type": "passage", "passage_id": str(p.id), "quote": p.quote, "paper_title": paper.title,
                                     "source_artifact_id": str(p.source_artifact_id) if p.source_artifact_id else None,
                                     "source_hash": p.source_hash})
                elif s.result_ref:
                    rkey, _, metric = s.result_ref.partition(":")
                    rr = results.get(rkey)
                    evidence.append({"type": "result", "result_key": rkey, "metric": metric or None,
                                     "artifact_id": rr["artifact_id"] if rr else None,
                                     "wording_limits": rr["wording_limits"] if rr else [],
                                     "assurance": rr["assurance"] if rr else None})
            linked = [{"span_id": s.span_id, "text": s.text, "kind": s.kind, "section": s.section_key}
                      for s in spans if key in s.claim_ids]
            items.append({"key": key, "proposition": c.proposition, "kind": c.kind, "category": c.category,
                          "critical": bool(c.critical), "evidence": evidence, "spans": linked})
        prior = {}
        for rec in (await ctx.db.execute(select(ClaimCheckRecord).where(ClaimCheckRecord.project_id == project.id)
                                          .order_by(ClaimCheckRecord.created_at))).scalars():
            prior[rec.check_key] = {"id": str(rec.id), "source_status": rec.source_status, "source_detail": rec.source_detail,
                                    "meaning": rec.meaning, "method": rec.method}
        return {**base, "claims": items, "prior_checks": prior, "sampling_rule": SAMPLING_RULE}
    if function == "technical":
        inst = await active_instance(ctx.db, project.id)
        fp = await frozen_protocol(ctx.db, inst.id) if inst else None
        return {**base, "results": await _results(ctx.db, project.id), "frozen_protocol_hash": fp.content_hash if fp else None,
                "cited_result_keys": sorted({k for s in spans for k in s.result_keys})}
    # compliance: reads the official rules and snapshot texts directly, plus the compile run of this version
    from .cfp import current_ruleset
    from .templates import confirmed_template

    rules = []
    cfp_available = project.target_edition_id is not None
    ruleset_art = None
    if cfp_available:
        rs = await current_ruleset(ctx.db, project)
        rows = {str(x.id): x for x in (await ctx.db.execute(select(CfpRule).where(
            CfpRule.id.in_([uuid.UUID(x["id"]) for x in rs["rules"]])))).scalars()} if rs["rules"] else {}
        snaps = {s.id: s for s in (await ctx.db.execute(select(SourceSnapshot).where(
            SourceSnapshot.id.in_({x.snapshot_id for x in rows.values()})))).scalars()} if rows else {}
        for x in rs["rules"]:
            if x["status"] in ("rejected", "superseded", "not_applicable") or (x.get("resolution") or {}).get("action") in (
                    "reject", "not_applicable"):
                continue
            row = rows[x["id"]]
            snap = snaps.get(row.snapshot_id)
            res = x.get("resolution") or {}
            rules.append({"id": x["id"], "rule_key": x["rule_key"], "status": x["status"], "blocking": x["blocking"],
                          "value": res.get("value") or x["value"], "value_text": res.get("value_text") or x["value_text"],
                          "quote": row.quote, "snapshot_text_artifact_id": str(snap.text_artifact_id) if snap and snap.text_artifact_id else None,
                          "snapshot_artifact_id": str(snap.artifact_id) if snap else None,
                          "snapshot_url": snap.url if snap else None})
        ruleset_art = (await ctx.db.execute(select(Artifact).where(Artifact.project_id == project.id, Artifact.kind == "cfp_ruleset",
                                                                   Artifact.freshness == "current")
                                            .order_by(Artifact.created_at.desc()))).scalars().first()
        cfp_available = bool(rules) and ruleset_art is not None
    tpl = await confirmed_template(ctx.db, project.id)
    run = await manuscript_compile_run(ctx.db, project.id, v.id)
    return {**base, "cfp_available": cfp_available, "rules": rules,
            "ruleset_artifact_id": str(ruleset_art.id) if ruleset_art else None,
            "template": {"id": str(tpl.id), "family": tpl.family, "archive_hash": tpl.archive_hash,
                         "archive_artifact_id": str(tpl.archive_artifact_id)} if tpl else None,
            "compile_run": {"id": str(run.id), "status": run.status, "pages": run.pages, "options": run.options,
                            "checks": {c["id"]: c["status"] for c in run.checks},
                            "report_artifact_id": str(run.report_artifact_id)} if run else None,
            "manuscript": {"abstract_words": word_count(section_text(content.section("abstract"))),
                           "sections": {s.key: bool(section_text(s).strip()) for s in content.sections}}}


class ReportIn(BaseModel):
    status: str = Field(pattern="^(performed|partial|not_performed)$")
    artifact_id: uuid.UUID
    findings: list[Finding] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    assessed_ok: dict[str, Any] = Field(default_factory=dict)
    input_hashes: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    claim_checks: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/internal/reviews/{round_id}/reports/{function}", status_code=201)
async def freeze_report(round_id: uuid.UUID, function: str, body: ReportIn, ctx: Ctx = Depends(service_ctx)):
    r, project = await _internal_round(ctx, round_id)
    require_service_scope(ctx, r.project_id, "domain.write")
    if function not in r.functions:
        raise not_found("function")
    existing = (await ctx.db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id,
                                                                ReviewReport.function == function))).scalar_one_or_none()
    if existing is not None:
        return {"id": str(existing.id), "frozen": True, "replayed": True}
    await art_svc.require_committed(ctx.db, [body.artifact_id], r.project_id)
    rep = ReviewReport(tenant_id=project.tenant_id, round_id=r.id, function=function, status=body.status,
                       artifact_id=body.artifact_id, frozen_at=utcnow(), input_hashes=body.input_hashes, summary=body.summary,
                       assessed_ok=body.assessed_ok, provenance=body.provenance)
    ctx.db.add(rep)
    await ctx.db.flush()
    prior = list((await ctx.db.execute(select(ReviewFinding).where(
        ReviewFinding.project_id == r.project_id, ReviewFinding.function == function,
        ReviewFinding.status.in_(["accepted_risk", "rejected_with_reason"])))).scalars())
    for f in body.findings:
        row = ReviewFinding(tenant_id=project.tenant_id, round_id=r.id, report_id=rep.id, project_id=r.project_id,
                            function=function, severity=f.severity, category=f.category, title=f.title, rationale=f.rationale,
                            check=f.check, proposed_fix=f.proposed_fix, span_ids=f.span_ids, claim_ids=f.claim_ids,
                            artifact_ids=f.artifact_ids, rule_ids=f.rule_ids)
        # A researcher's decision carries forward only for the identical finding on unchanged spans/claims.
        same = next((p for p in prior if p.category == f.category and p.title == f.title and p.severity == f.severity
                     and sorted(p.span_ids) == sorted(f.span_ids) and sorted(p.claim_ids) == sorted(f.claim_ids)), None)
        if same is not None and f.category not in MUST_FIX:
            row.status, row.resolved_by, row.resolved_at = same.status, same.resolved_by, same.resolved_at
            row.resolution_note = f"carried forward (unchanged text): {same.resolution_note}"
            row.resolved_in_version = same.resolved_in_version
        ctx.db.add(row)
    prior_checks = {c.check_key: c.id for c in (await ctx.db.execute(select(ClaimCheckRecord).where(
        ClaimCheckRecord.project_id == r.project_id))).scalars()}
    for c in body.claim_checks:
        ctx.db.add(ClaimCheckRecord(tenant_id=project.tenant_id, project_id=r.project_id, round_id=r.id, claim_key=c["claim_key"],
                                    check_key=c["check_key"], critical=c["critical"], selection=c["selection"],
                                    source_status=c["source_status"], source_detail=c["source_detail"], meaning=c["meaning"],
                                    method=c["method"], reused_from=prior_checks.get(c["check_key"]) if c.get("reused") else None))
    await ctx.db.commit()
    return {"id": str(rep.id), "frozen": True}


@router.get("/internal/reviews/{round_id}/frozen-reports")
async def frozen_reports(round_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    """Meta-review input: available only after every function froze its own report."""
    r, _ = await _internal_round(ctx, round_id)
    reps = {x.function: x for x in (await ctx.db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id))).scalars()}
    if set(r.functions) - set(reps):
        raise conflict("reports_not_frozen", "the meta-review waits for every frozen report",
                       {"missing": sorted(set(r.functions) - set(reps))})
    out = {}
    for f, rep in reps.items():
        fs = (await ctx.db.execute(select(ReviewFinding).where(ReviewFinding.report_id == rep.id))).scalars()
        out[f] = {"status": rep.status, "artifact_id": str(rep.artifact_id), "assessed_ok": rep.assessed_ok,
                  "not_performed_detail": rep.summary.get("reason"),
                  "findings": [{"severity": x.severity, "span_ids": x.span_ids, "claim_ids": x.claim_ids} for x in fs]}
    return {"reports": out}


class MetaIn(BaseModel):
    artifact_id: uuid.UUID
    meta: dict[str, Any]


@router.post("/internal/reviews/{round_id}/meta")
async def record_meta(round_id: uuid.UUID, body: MetaIn, ctx: Ctx = Depends(service_ctx)):
    r, _ = await _internal_round(ctx, round_id)
    require_service_scope(ctx, r.project_id, "domain.write")
    await art_svc.require_committed(ctx.db, [body.artifact_id], r.project_id)
    if r.status != "complete":
        r.meta, r.meta_artifact_id, r.status = body.meta, body.artifact_id, "complete"
    await ctx.db.commit()
    return {"id": str(r.id), "status": r.status}


# --------------------------------------------------------------------------- internal: integrity
@router.get("/internal/integrity-reports/{report_id}/bundle")
async def integrity_bundle(report_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_task_kind(ctx, "integrity_check")
    rep = (await ctx.db.execute(select(IntegrityReport).where(IntegrityReport.id == report_id))).scalar_one_or_none()
    if rep is None:
        raise not_found("integrity report")
    require_service_scope(ctx, rep.project_id, "domain.read")
    project, _ = await project_for(ctx, rep.project_id)
    v = (await ctx.db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == rep.manuscript_version_id))).scalar_one()
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, v.artifact_id))
    content = ManuscriptContent.model_validate(data["content"])
    spans = list((await ctx.db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == v.id)
                                       .order_by(ManuscriptSpan.position))).scalars())
    bib = list((await ctx.db.execute(select(BibliographyEntry, TenantPaperRecord).join(
        TenantPaperRecord, TenantPaperRecord.id == BibliographyEntry.paper_id).where(
        BibliographyEntry.project_id == project.id, BibliographyEntry.is_current.is_(True)))).all())
    results = await _results(ctx.db, project.id)
    inst = await active_instance(ctx.db, project.id)
    fp = await frozen_protocol(ctx.db, inst.id) if inst else None
    amendments = [{"version": p.version_number, "rationale": p.amendment_rationale}
                  for p in (await ctx.db.execute(select(Protocol).where(Protocol.method_instance_id == inst.id,
                                                                        Protocol.after_data_inspection.is_(True)))).scalars()] if inst else []
    contribs = list((await ctx.db.execute(select(Contribution).where(Contribution.project_id == project.id))).scalars())
    tpl_note = None
    from .templates import confirmed_template

    tpl = await confirmed_template(ctx.db, project.id)
    if tpl:
        tpl_note = tpl.license_note
    passages = list((await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.project_id == project.id))).scalars())
    source_ids = sorted({str(p.source_artifact_id) for p in passages if p.source_artifact_id})
    figures = []
    for s in content.sections:
        for f in s.figures:
            ok = (await ctx.db.execute(select(Artifact).where(Artifact.id == uuid.UUID(f.artifact_id),
                                                              Artifact.project_id == project.id,
                                                              Artifact.status == "available"))).scalar_one_or_none()
            figures.append({"file_name": f.file_name, "artifact_id": f.artifact_id, "committed": ok is not None})
    emails = [u.email for u, _ in (await ctx.db.execute(select(User, ProjectMember).join(
        ProjectMember, ProjectMember.user_id == User.id).where(ProjectMember.project_id == project.id))).all()]
    declarations = None
    try:
        from .submission import declarations_for  # M8 author records and disclosures

        declarations = await declarations_for(ctx.db, project.id)
    except ImportError:
        pass
    return {
        "manuscript_version": v.version_number, "manuscript_artifact_id": str(v.artifact_id),
        "spans": _spans_json(spans),
        "bibliography": [{"cite_key": b.cite_key, "identity_status": p.identity_status, "retracted": bool(p.retracted),
                          "doi": p.doi} for b, p in bib],
        "results": {k: {"assurance": r_["assurance"], "protocol_hash": r_["manifest"].get("protocol_hash"),
                        "data_origin": r_["manifest"].get("data_origin"), "data_rights": r_["manifest"].get("data_rights"),
                        "assessment_blockers": r_["assessment_blockers"],
                        "failed_checks": [c for c in r_["assessment_checks"] if c.get("status") == "failed"]}
                    for k, r_ in results.items()},
        "frozen_protocol_hash": fp.content_hash if fp else None,
        "protocol": {"ethics_rights": fp.ethics_rights if fp else None, "after_data_inspection_amendments": amendments},
        "contributions": [{"title": c.title, "pii_classification": c.pii_classification, "rights_statement": c.rights_statement}
                          for c in contribs],
        "figures": figures, "source_artifact_ids": source_ids, "template": {"license_note": tpl_note},
        "authors_emails": emails, "declarations": declarations,
    }


class IntegrityIn(BaseModel):
    artifact_id: uuid.UUID
    checks: list[IntegrityCheck]


@router.post("/internal/integrity-reports/{report_id}")
async def record_integrity(report_id: uuid.UUID, body: IntegrityIn, ctx: Ctx = Depends(service_ctx)):
    require_task_kind(ctx, "integrity_check")
    rep = (await ctx.db.execute(select(IntegrityReport).where(IntegrityReport.id == report_id))).scalar_one_or_none()
    if rep is None:
        raise not_found("integrity report")
    require_service_scope(ctx, rep.project_id, "domain.write")
    await art_svc.require_committed(ctx.db, [body.artifact_id], rep.project_id)
    if rep.status != "complete":
        rep.artifact_id, rep.checks, rep.status = body.artifact_id, [c.model_dump() for c in body.checks], "complete"
    await ctx.db.commit()
    return {"id": str(rep.id), "status": rep.status}


_ = (content_hash, ComplianceCheck)
