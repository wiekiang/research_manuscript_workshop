"""M5 - authoritative study type / method workflow selection, H1, protocols, methodology review, H2, method stages."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts import methods
from rp_contracts.contribution import ETHICS_DECLARATION_TEXT, EthicsRightsDeclaration, ethics_blockers
from rp_contracts.enums import Gate, LedgerCategory, ProjectState

from ..db.base import utcnow
from ..db.models.cfp import Track
from ..db.models.contribution import (
    Contribution,
    MethodStageOutput,
    MethodWorkflowInstance,
    Protocol,
    ResultAssessmentRecord,
    ResultManifestRecord,
)
from ..db.models.core import Artifact, Project
from ..db.models.literature import (
    FeasibilityAssessment,
    LiteratureCoverageAssessment,
    Opportunity,
    PaperRationale,
    ScreeningDecision,
    StudyTypeRecommendation,
)
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import approvals as approval_svc
from ..services import artifacts as art_svc
from ..services import budget as budget_svc
from ..services import invalidation, ledger
from ..services.approvals import DECLARATIONS
from ..services.common import audit
from ..services.gates import GateResult, gate
from ..services.tasks import create_task
from ..services.transitions import TransitionRequest, request_transition
from .opportunities import _accepts

router = APIRouter(tags=["method"])
MIN_REASONING = 40


async def active_instance(db: AsyncSession, project_id: uuid.UUID) -> MethodWorkflowInstance | None:
    return (await db.execute(select(MethodWorkflowInstance).where(MethodWorkflowInstance.project_id == project_id,
                                                                  MethodWorkflowInstance.status == "active"))).scalars().first()


def definition_of(inst: MethodWorkflowInstance) -> methods.ResearchWorkflowDefinition:
    return methods.REGISTRY[inst.definition_key]


def instance_out(i: MethodWorkflowInstance | None) -> dict | None:
    if i is None:
        return None
    d = definition_of(i)
    return {"id": str(i.id), "definition_key": i.definition_key, "study_type": i.study_type, "title": d.title,
            "definition_version": i.definition_version, "venue_category": i.venue_category,
            "enabled_for_submission_ready": i.enabled_for_submission_ready, "availability": d.availability,
            "planning_only_reason": d.planning_only_reason, "status": i.status, "track_accepts": i.track_accepts,
            "selection_rationale": i.selection_rationale, "override_of_recommendation": i.override_of_recommendation,
            "reuse_decisions": i.reuse_decisions, "frozen_at": i.frozen_at, "created_at": i.created_at}


# --------------------------------------------------------------------------- study type / method selection
class SelectIn(BaseModel):
    study_type: str
    venue_category: str
    opportunity_id: uuid.UUID | None = None
    rationale: str | None = Field(default=None, max_length=8000)


@router.post("/projects/{project_id}/study-type/select", status_code=201)
async def select_study_type(project_id: uuid.UUID, body: SelectIn, ctx: Ctx = Depends(user_ctx)):
    """Select (or switch) the study type and venue category. A switch creates a new method-workflow instance and
    reopens H1 and everything downstream; prior H2/H3 approvals never transfer."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    try:
        d = methods.latest(body.study_type)
    except KeyError as exc:
        raise unprocessable("unknown_study_type", f"unknown study type {body.study_type}") from exc
    if body.venue_category not in methods.VENUE_CATEGORIES:
        raise unprocessable("unknown_venue_category", "choose a venue category from the CFP-supported list",
                            {"allowed": list(methods.VENUE_CATEGORIES)})
    track = (await ctx.db.execute(select(Track).where(Track.id == project.target_track_id))).scalar_one_or_none() \
        if project.target_track_id else None
    accepts, ref = _accepts(track, body.venue_category)
    if accepts == "no":
        raise unprocessable("venue_category_not_accepted", "the selected track does not accept this submission category",
                            ref)
    recommended = set()
    if body.opportunity_id:
        recs = (await ctx.db.execute(select(StudyTypeRecommendation).where(
            StudyTypeRecommendation.opportunity_id == body.opportunity_id))).scalars().all()
        recommended = {(r.study_type, r.venue_category) for r in recs}
    override = bool(recommended) and (body.study_type, body.venue_category) not in recommended
    if (override or accepts == "unknown") and not (body.rationale and len(body.rationale.strip()) >= 20):
        raise unprocessable("rationale_required", "explain this choice (it differs from the advice or the track's "
                                                  "acceptance of this category is unknown)")
    current = await active_instance(ctx.db, project_id)
    if current and current.study_type == d.study_type and current.venue_category == body.venue_category:
        return instance_out(current)
    inst = MethodWorkflowInstance(tenant_id=ctx.tenant_id, project_id=project_id, definition_key=d.key,
                                  study_type=d.study_type, definition_version=d.definition_version,
                                  venue_category=body.venue_category,
                                  enabled_for_submission_ready=d.enabled_for_submission_ready,
                                  opportunity_id=body.opportunity_id, selection_rationale=body.rationale,
                                  override_of_recommendation=override, track_accepts=accepts,
                                  selected_by=ctx.principal.user_id, supersedes_id=current.id if current else None)
    effects: dict[str, Any] = {}
    if current is not None:
        current.status = "superseded"
        inst.reuse_decisions = await _reuse_proposals(ctx.db, project_id, current, d)
        roots = [a.id for a in (await ctx.db.execute(select(Artifact).where(
            Artifact.project_id == project_id, Artifact.kind.in_(["research_direction", "protocol"]),
            Artifact.freshness == "current"))).scalars()]
        for p in (await ctx.db.execute(select(Protocol).where(Protocol.method_instance_id == current.id))).scalars():
            p.status = "superseded"
        if roots:
            res = await invalidation.invalidate(ctx.db, ctx.principal, project, roots,
                                                f"study type changed from {current.study_type} to {d.study_type}",
                                                f"method-switch:{inst.id}")
            effects = res.as_dict()
    ctx.db.add(inst)
    await ctx.db.flush()
    project.method_instance_id = inst.id
    project.version += 1
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.METHODOLOGY_EDIT,
                         f"Selected study type {d.title} / venue category {body.venue_category}",
                         source_action="method.select", rationale=body.rationale,
                         rationale_requested=not bool(body.rationale))
    await audit(ctx.db, ctx.principal, "method.selected", project_id=project_id, resource_type="method_instance",
                resource_id=inst.id, details={"definition": d.key, "venue_category": body.venue_category,
                                              "switch_from": current.definition_key if current else None})
    await ctx.db.commit()
    return {**instance_out(inst), "switch_effects": effects}


async def _reuse_proposals(db, project_id, old: MethodWorkflowInstance, new_def) -> list[dict]:
    """Evidence may be proposed for reuse after compatibility checks; screening decisions from a non-systematic
    method never become systematic screening decisions."""
    out = [{"item": "bibliographic metadata and verified evidence passages", "decision": "proposed_for_reuse",
            "reason": "provenance preserved; researcher confirms compatibility with the new method"}]
    systematic = {"systematic_review", "meta_analysis", "mapping_review", "scoping_review", "tertiary_review"}
    screened = (await db.execute(select(ScreeningDecision).where(ScreeningDecision.project_id == project_id,
                                                                 ScreeningDecision.is_current.is_(True)))).scalars().all()
    if screened and new_def.study_type in systematic and old.study_type not in systematic:
        for s in screened:
            s.is_current = False
        out.append({"item": f"{len(screened)} screening decisions", "decision": "not_transferred",
                    "reason": "narrative/informal paper choices cannot become systematic screening decisions"})
    out.append({"item": "H2/H3 approvals, protocols and method-stage outputs", "decision": "not_transferred",
                "reason": "approvals and protocol-bound outputs belong to the previous method instance"})
    return out


@router.get("/projects/{project_id}/workflow-definition")
async def workflow_definition(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    inst = await active_instance(ctx.db, project_id)
    if inst is None:
        return {"instance": None, "definition": None, "stages": []}
    d = definition_of(inst)
    frozen = await frozen_protocol(ctx.db, inst.id)
    outputs = {} if frozen is None else {o.stage_id: o for o in (await ctx.db.execute(select(MethodStageOutput).where(
        MethodStageOutput.method_instance_id == inst.id, MethodStageOutput.protocol_id == frozen.id,
        MethodStageOutput.is_current.is_(True)))).scalars()}
    stages = []
    for s in d.required_stages:
        o = outputs.get(s.id)
        stages.append({**s.model_dump(), "required": True,
                       "status": o.status if o else ("blocked_until_h2" if frozen is None else "not_started"),
                       "output_artifact_id": str(o.artifact_id) if o else None,
                       "validator_results": o.validator_results if o else []})
    return {"instance": instance_out(inst), "definition": d.model_dump(), "stages": stages,
            "frozen_protocol_version": frozen.version_number if frozen else None}


# --------------------------------------------------------------------------- H1 research direction
class DirectionIn(BaseModel):
    opportunity_id: uuid.UUID
    research_question: str = Field(min_length=10, max_length=4000)
    intended_contribution: str = Field(min_length=10, max_length=8000)
    how_it_differs: str = Field(description="your reasoning about how this differs from the nearest prior work")
    method_rationale: str = Field(description="why this study type answers the question")
    rationale_approved: bool = False
    feasibility_rationale: str | None = None
    declaration_accepted: bool
    declaration_text: str


async def h1_preconditions(db: AsyncSession, project: Project, body: DirectionIn | None = None) -> list[str]:
    reasons = []
    inst = await active_instance(db, project.id)
    if inst is None:
        reasons.append("select a study type and venue category")
    elif inst.track_accepts == "no":
        reasons.append("the selected track does not accept the chosen submission category")
    if body is None:
        return reasons
    opp = (await db.execute(select(Opportunity).where(Opportunity.id == body.opportunity_id,
                                                      Opportunity.project_id == project.id))).scalar_one_or_none()
    if opp is None:
        reasons.append("choose one of the project's opportunity proposals")
        return reasons
    rat = (await db.execute(select(PaperRationale).where(PaperRationale.opportunity_id == opp.id,
                                                         PaperRationale.is_current.is_(True)))).scalars().first()
    if rat is None:
        reasons.append("the Paper Rationale is missing")
    elif rat.status == "draft" and not body.rationale_approved:
        reasons.append("edit the Paper Rationale or explicitly approve its reasoning")
    if not opp.closest_work:
        reasons.append("nearest prior work has not been identified")
    feas = (await db.execute(select(FeasibilityAssessment).where(FeasibilityAssessment.opportunity_id == opp.id,
                                                                 FeasibilityAssessment.is_current.is_(True)))).scalars().first()
    if feas is None:
        reasons.append("the feasibility assessment is missing")
    elif feas.status != "feasible" and not (body.feasibility_rationale and len(body.feasibility_rationale.strip()) >= 20):
        reasons.append(f"feasibility is {feas.status}: record why you proceed")
    if len(body.how_it_differs.strip()) < MIN_REASONING:
        reasons.append("explain in your own words how this differs from the nearest prior work")
    if len(body.method_rationale.strip()) < 20:
        reasons.append("explain why the selected study type can answer the question")
    return reasons


@router.post("/projects/{project_id}/direction/approve")
async def approve_direction(project_id: uuid.UUID, body: DirectionIn, ctx: Ctx = Depends(user_ctx)):
    """H1: the researcher's substantive decision on question, intended contribution and method."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    if project.state != ProjectState.DIRECTION_REVIEW:
        raise conflict("wrong_state", f"H1 is recorded in DIRECTION_REVIEW (project is {project.state})")
    reasons = await h1_preconditions(ctx.db, project, body)
    if reasons:
        raise ApiError(422, "gate_unsatisfied", "H1 preconditions are not met", {"reasons": reasons})
    inst = await active_instance(ctx.db, project_id)
    opp = (await ctx.db.execute(select(Opportunity).where(Opportunity.id == body.opportunity_id))).scalar_one()
    rat = (await ctx.db.execute(select(PaperRationale).where(PaperRationale.opportunity_id == opp.id,
                                                             PaperRationale.is_current.is_(True)))).scalars().first()
    feas = (await ctx.db.execute(select(FeasibilityAssessment).where(FeasibilityAssessment.opportunity_id == opp.id,
                                                                     FeasibilityAssessment.is_current.is_(True)))).scalars().first()
    if rat.status == "draft":
        rat.status = "approved"
    feas_art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "feasibility_assessment",
                                           {"opportunity_id": str(opp.id), "status": feas.status, "deadlines": feas.deadlines,
                                            "estimates": feas.estimates, "cost_estimate": feas.cost_estimate,
                                            "constraints": feas.constraints, "assumptions": feas.assumptions,
                                            "uncertainty": feas.uncertainty, "slack_days": feas.slack_days,
                                            "researcher_rationale": body.feasibility_rationale},
                                           label="Feasibility assessment (at H1)")).artifact
    feas.artifact_id = feas_art.id
    cov = (await ctx.db.execute(select(LiteratureCoverageAssessment).where(
        LiteratureCoverageAssessment.project_id == project_id).order_by(
        LiteratureCoverageAssessment.assessment_version.desc()))).scalars().first()
    direction = {
        "opportunity_id": str(opp.id), "research_question": body.research_question,
        "intended_contribution": body.intended_contribution, "how_it_differs": body.how_it_differs,
        "method_rationale": body.method_rationale, "closest_work": opp.closest_work, "novelty_caveat": opp.novelty_caveat,
        "study_type": inst.study_type, "venue_category": inst.venue_category, "method_definition": inst.definition_key,
        "rationale_artifact_id": str(rat.artifact_id), "feasibility_artifact_id": str(feas_art.id),
        "coverage_artifact_id": str(cov.artifact_id) if cov else None,
        "label": "Proposed contribution: novelty is a hypothesis supported by the documented search",
    }
    deps = [a for a in (rat.artifact_id, feas_art.id, cov.artifact_id if cov else None) if a]
    dir_art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "research_direction", direction,
                                          depends_on=deps, label="Research direction (H1)")).artifact
    rat_art = await art_svc.get_artifact(ctx.db, rat.artifact_id, project_id)
    appr = await approval_svc.record_approval(ctx.db, ctx.principal, project, Gate.H1, [dir_art, rat_art, feas_art],
                                              declaration_accepted=body.declaration_accepted,
                                              declaration_text=body.declaration_text, rationale=body.how_it_differs)
    opp.status = "selected"
    old_q = rat.research_question
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.QUESTION_REFINEMENT,
                         "Decided the research direction at H1", source_action="direction.approve",
                         diff=ledger.text_diff(old_q, body.research_question, "research question"),
                         rationale=f"{body.how_it_differs}\n\nMethod: {body.method_rationale}", rationale_requested=False,
                         artifact_id=dir_art.id)
    res = await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
        requested_state=ProjectState.PROTOCOL_REVIEW, expected_project_version=project.version,
        idempotency_key=f"h1:{appr.id}", human_approval_id=appr.id, cause="approval",
        method_definition_version=inst.definition_key))
    await ctx.db.commit()
    return {"approval_id": str(appr.id), "direction_artifact_id": str(dir_art.id), "transition": res.as_dict()}


@gate("h1.approved")
async def h1_gate(db: AsyncSession, project: Project) -> GateResult:
    appr, problems = await approval_svc.current_approval(db, project.id, Gate.H1)
    reasons = list(problems) + await h1_preconditions(db, project)
    if appr is None or reasons:
        return GateResult("h1.approved", False, reasons, next_action="Review the direction and record H1")
    return GateResult("h1.approved", True, evidence={"approval_id": str(appr.id)})


# --------------------------------------------------------------------------- protocols
class ProtocolIn(BaseModel):
    sections: dict[str, str]
    ethics_rights: EthicsRightsDeclaration | None = None
    compute_estimate: str | None = None
    cost_estimate_cents: int | None = Field(default=None, ge=0)
    amendment_rationale: str | None = None
    after_data_inspection: bool = False


async def frozen_protocol(db: AsyncSession, instance_id: uuid.UUID) -> Protocol | None:
    return (await db.execute(select(Protocol).where(Protocol.method_instance_id == instance_id,
                                                    Protocol.status == "frozen"))).scalars().first()


def protocol_validation(p: Protocol, d: methods.ResearchWorkflowDefinition, budget_remaining: int) -> dict:
    missing = [s for s in d.protocol_sections if s != "ethics_rights_declaration" and not (p.sections.get(s) or "").strip()]
    for check in PROTOCOL_CHECKS:
        missing += [x for x in check(p, d) if not x.endswith("is empty")]
    eth = EthicsRightsDeclaration.model_validate(p.ethics_rights) if p.ethics_rights else None
    eblock = ethics_blockers(eth)
    cost = []
    if p.cost_estimate_cents is not None and p.cost_estimate_cents > budget_remaining:
        cost.append(f"estimated platform cost {p.cost_estimate_cents} cents exceeds the remaining budget "
                    f"({budget_remaining}); an explicit cap decision is needed")
    review = [] if p.review_status in ("performed", "waived") else [
        "independent methodology review not performed (request it, or record a waiver with rationale)"]
    blocking_issues = [i for i in p.review_issues if i.get("severity") == "blocker" and not i.get("resolved")]
    return {"missing_sections": missing, "ethics_blockers": eblock, "cost_flags": cost, "review": review,
            "unresolved_blocker_issues": blocking_issues,
            "ready_for_h2": not (missing or eblock or cost or review or blocking_issues)}


def protocol_out(p: Protocol, validation: dict | None = None) -> dict:
    return {"id": str(p.id), "version": p.version_number, "status": p.status, "sections": p.sections,
            "ethics_rights": p.ethics_rights, "compute_estimate": p.compute_estimate,
            "cost_estimate_cents": p.cost_estimate_cents, "artifact_id": str(p.artifact_id), "content_hash": p.content_hash,
            "is_amendment": p.is_amendment, "amendment_rationale": p.amendment_rationale,
            "after_data_inspection": p.after_data_inspection, "frozen_at": p.frozen_at, "review_status": p.review_status,
            "review_issues": p.review_issues, "review_waiver_rationale": p.review_waiver_rationale,
            "created_at": p.created_at, "validation": validation, "ethics_declaration_text": ETHICS_DECLARATION_TEXT}


@router.post("/projects/{project_id}/protocols", status_code=201)
async def create_protocol(project_id: uuid.UUID, body: ProtocolIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    inst = await active_instance(ctx.db, project_id)
    if inst is None:
        raise unprocessable("no_method", "select the study type first")
    appr, problems = await approval_svc.current_approval(ctx.db, project_id, Gate.H1)
    if appr is None or problems:
        raise unprocessable("h1_required", "record the H1 research direction before drafting the protocol")
    versions = list((await ctx.db.execute(select(Protocol).where(Protocol.method_instance_id == inst.id)
                                          .order_by(Protocol.version_number))).scalars())
    frozen = next((v for v in versions if v.status == "frozen"), None)
    if frozen is not None and not (body.amendment_rationale and len(body.amendment_rationale.strip()) >= 20):
        raise unprocessable("amendment_rationale_required", "the protocol is frozen; a change is a dated amendment with a rationale")
    content = {"method_definition": inst.definition_key, "sections": body.sections,
               "ethics_rights": body.ethics_rights.model_dump() if body.ethics_rights else None,
               "compute_estimate": body.compute_estimate, "cost_estimate_cents": body.cost_estimate_cents,
               "amendment": {"rationale": body.amendment_rationale, "after_data_inspection": body.after_data_inspection,
                             "date": utcnow().date().isoformat()} if frozen else None,
               "version": (versions[-1].version_number + 1) if versions else 1}
    dir_art = (await ctx.db.execute(select(Artifact).where(Artifact.project_id == project_id,
                                                           Artifact.kind == "research_direction",
                                                           Artifact.freshness == "current")
                                    .order_by(Artifact.created_at.desc()))).scalars().first()
    pub = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "protocol", content,
                                      depends_on=[dir_art.id] if dir_art else None,
                                      label=f"Protocol v{content['version']}{' (amendment)' if frozen else ''}")).artifact
    p = Protocol(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id,
                 version_number=content["version"], status="draft", sections=body.sections,
                 ethics_rights=content["ethics_rights"], compute_estimate=body.compute_estimate,
                 cost_estimate_cents=body.cost_estimate_cents, artifact_id=pub.id, content_hash=pub.content_hash,
                 is_amendment=frozen is not None, amendment_rationale=body.amendment_rationale,
                 after_data_inspection=body.after_data_inspection, created_by=ctx.principal.user_id)
    ctx.db.add(p)
    await ctx.db.flush()
    prev = versions[-1] if versions else None
    diff = "\n".join(ledger.text_diff((prev.sections if prev else {}).get(k), v, k) or "" for k, v in body.sections.items())
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.METHODOLOGY_EDIT,
                         f"{'Amended' if frozen else 'Drafted'} protocol v{p.version_number}", source_action="protocol.save",
                         diff=diff or None, rationale=body.amendment_rationale, artifact_id=pub.id)
    await ctx.db.commit()
    st = await budget_svc.status(ctx.db, project)
    return protocol_out(p, protocol_validation(p, definition_of(inst), st.remaining_cents))


@router.get("/projects/{project_id}/protocols")
async def list_protocols(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    inst = await active_instance(ctx.db, project_id)
    if inst is None:
        return {"items": [], "required_sections": []}
    st = await budget_svc.status(ctx.db, project)
    rows = (await ctx.db.execute(select(Protocol).where(Protocol.method_instance_id == inst.id)
                                 .order_by(Protocol.version_number.desc()))).scalars()
    d = definition_of(inst)
    return {"items": [protocol_out(p, protocol_validation(p, d, st.remaining_cents)) for p in rows],
            "required_sections": d.protocol_sections, "declaration": DECLARATIONS[Gate.H2].text}


async def _protocol(db, project_id, version) -> Protocol:
    inst = await active_instance(db, project_id)
    p = (await db.execute(select(Protocol).where(Protocol.method_instance_id == (inst.id if inst else None),
                                                 Protocol.version_number == version))).scalar_one_or_none()
    if p is None:
        raise not_found("protocol version")
    return p


@router.post("/projects/{project_id}/protocols/{version}/review", status_code=202)
async def request_review(project_id: uuid.UUID, version: int, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    p = await _protocol(ctx.db, project_id, version)
    task, _ = await create_task(ctx.db, ctx.principal, project, "methodology_review",
                                {"protocol_id": str(p.id), "version": version}, input_manifest={"protocol": p.content_hash})
    p.review_status = "requested"
    await ctx.db.commit()
    return {"task": task_out(task)}


class WaiveIn(BaseModel):
    rationale: str = Field(min_length=30, max_length=4000)


@router.post("/projects/{project_id}/protocols/{version}/waive-review")
async def waive_review(project_id: uuid.UUID, version: int, body: WaiveIn, ctx: Ctx = Depends(user_ctx)):
    """Record that independent review was not performed (e.g. no model configured) and why; shown at H2/H4."""
    await project_for(ctx, project_id, OWNER_ONLY)
    p = await _protocol(ctx.db, project_id, version)
    p.review_status = "waived"
    p.review_waiver_rationale = body.rationale
    await audit(ctx.db, ctx.principal, "protocol.review_waived", project_id=project_id, details={"version": version})
    await ctx.db.commit()
    return protocol_out(p)


class ResolveIssueIn(BaseModel):
    index: int
    resolution: str = Field(pattern="^(fixed|accepted_risk|rejected_with_reason)$")
    note: str = Field(min_length=5, max_length=4000)


@router.post("/projects/{project_id}/protocols/{version}/issues/resolve")
async def resolve_issue(project_id: uuid.UUID, version: int, body: ResolveIssueIn, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, OWNER_ONLY)
    p = await _protocol(ctx.db, project_id, version)
    issues = list(p.review_issues)
    if not 0 <= body.index < len(issues):
        raise not_found("issue")
    issues[body.index] = {**issues[body.index], "resolved": body.resolution, "resolution_note": body.note,
                          "resolved_by": str(ctx.principal.user_id)}
    p.review_issues = issues
    await ctx.db.commit()
    return protocol_out(p)


class FreezeIn(BaseModel):
    declaration_accepted: bool
    declaration_text: str
    rationale: str | None = None


@router.post("/projects/{project_id}/protocols/{version}/approve")
async def approve_protocol(project_id: uuid.UUID, version: int, body: FreezeIn, ctx: Ctx = Depends(user_ctx)):
    """H2: freeze this exact protocol version. Execution and results are bound to its hash."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    p = await _protocol(ctx.db, project_id, version)
    inst = await active_instance(ctx.db, project_id)
    st = await budget_svc.status(ctx.db, project)
    v = protocol_validation(p, definition_of(inst), st.remaining_cents)
    if not v["ready_for_h2"]:
        raise ApiError(422, "gate_unsatisfied", "the protocol is not ready to freeze", v)
    if p.status != "draft":
        raise conflict("not_draft", f"protocol v{version} is {p.status}")
    old = await frozen_protocol(ctx.db, inst.id)
    if old is not None:
        old.status = "superseded"
        await invalidation.invalidate(ctx.db, ctx.principal, project, [old.artifact_id],
                                      f"protocol amended (v{old.version_number} -> v{p.version_number}): "
                                      f"{p.amendment_rationale}", f"amend:{p.id}")
        for o in (await ctx.db.execute(select(MethodStageOutput).where(MethodStageOutput.protocol_id == old.id))).scalars():
            o.is_current = False
            o.status = "stale"
        await ctx.db.refresh(project)
    art = await art_svc.get_artifact(ctx.db, p.artifact_id, project_id)
    appr = await approval_svc.record_approval(ctx.db, ctx.principal, project, Gate.H2, [art],
                                              declaration_accepted=body.declaration_accepted,
                                              declaration_text=body.declaration_text, rationale=body.rationale)
    p.status = "frozen"
    p.frozen_at = utcnow()
    p.frozen_by = ctx.principal.user_id
    inst.frozen_at = p.frozen_at
    result = None
    if project.state == ProjectState.PROTOCOL_REVIEW:
        result = (await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
            requested_state=ProjectState.RESEARCH_ACTIVE, expected_project_version=project.version,
            idempotency_key=f"h2:{appr.id}", human_approval_id=appr.id, cause="approval",
            method_definition_version=inst.definition_key))).as_dict()
    await ctx.db.commit()
    return {"approval_id": str(appr.id), "protocol": protocol_out(p), "frozen_hash": p.content_hash, "transition": result}


# --------------------------------------------------------------------------- method stages
STAGE_TEXT_MIN = 80


def _text_ok(content: dict, key: str, n: int = STAGE_TEXT_MIN) -> bool:
    return len((content.get(key) or "").strip()) >= n


VALIDATORS = {
    "v.data_provenance_complete": lambda c, x: (all(_text_ok(c, k, 10) for k in ("data_origin", "selection_criteria"))
                                                and c.get("pii_classification") in ("none", "pseudonymized", "personal", "sensitive"),
                                                "data origin, selection criteria and PII classification recorded"),
    "v.rights_declared": lambda c, x: (_text_ok(c, "rights", 5), "data rights/licence declared"),
    "v.result_manifest_complete": lambda c, x: (bool(x["results"]), "at least one supplied result manifest attached"),
    "v.assurance_assessed": lambda c, x: (bool(x["results"]) and all(r["assessed"] for r in x["results"]),
                                          "every attached result has an assurance assessment"),
    "v.assumptions_stated": lambda c, x: (_text_ok(c, "description"), "definitions and assumptions recorded"),
    "v.argument_recorded": lambda c, x: (_text_ok(c, "description") and bool(x["contributions"]),
                                         "argument recorded with at least one supporting contribution file/note"),
    "v.evaluation_recorded": lambda c, x: (_text_ok(c, "description"), "evaluation (counterexamples, checks) recorded"),
    "v.method_specified": lambda c, x: (_text_ok(c, "description"), "method specification recorded"),
    "v.implementation_recorded": lambda c, x: (bool(x["contributions"]), "implementation or formal account attached"),
    "v.selection_documented": lambda c, x: (_text_ok(c, "description") and x["coverage"], "selection documented and a "
                                                                                           "coverage assessment exists"),
    "v.synthesis_recorded": lambda c, x: (_text_ok(c, "description", 200), "critical synthesis recorded"),
    "v.original_argument_recorded": lambda c, x: (_text_ok(c, "description", 120), "original argument stated"),
}


# DB-backed validators registered by later milestones (M10 evidence synthesis / qualitative): async (db, project,
# frozen_protocol, content, context) -> (ok, detail). Unknown validator ids fail closed.
ASYNC_VALIDATORS: dict = {}
# Extra protocol-readiness checks: (protocol, definition) -> list of problems.
PROTOCOL_CHECKS: list = []


class StageIn(BaseModel):
    description: str = Field(default="", max_length=50000)
    fields: dict[str, Any] = Field(default_factory=dict)
    contribution_ids: list[uuid.UUID] = Field(default_factory=list)
    result_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/projects/{project_id}/method-stages/{stage_id}", status_code=201)
async def submit_stage(project_id: uuid.UUID, stage_id: str, body: StageIn, ctx: Ctx = Depends(user_ctx)):
    """Record a required method stage. Outputs are validated deterministically; prose alone cannot complete a stage
    whose validator requires linked contributions or assessed results."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    inst = await active_instance(ctx.db, project_id)
    if inst is None:
        raise unprocessable("no_method", "select the study type first")
    d = definition_of(inst)
    stage = next((s for s in d.required_stages + d.optional_stages if s.id == stage_id), None)
    if stage is None:
        raise not_found("stage")
    frozen = await frozen_protocol(ctx.db, inst.id)
    if frozen is None:
        raise unprocessable("h2_required", "method stages run only against the frozen (H2-approved) protocol")
    done = {o.stage_id for o in (await ctx.db.execute(select(MethodStageOutput).where(
        MethodStageOutput.protocol_id == frozen.id, MethodStageOutput.is_current.is_(True),
        MethodStageOutput.status == "validated"))).scalars()}
    missing_pred = [p for p in stage.predecessor_stage_ids if p not in done]
    if missing_pred:
        raise unprocessable("predecessors_incomplete", f"complete {missing_pred} first")
    contribs = list((await ctx.db.execute(select(Contribution).where(Contribution.id.in_(body.contribution_ids),
                                                                     Contribution.project_id == project_id)))
                    .scalars()) if body.contribution_ids else []
    results = list((await ctx.db.execute(select(ResultManifestRecord).where(
        ResultManifestRecord.id.in_(body.result_ids), ResultManifestRecord.project_id == project_id,
        ResultManifestRecord.is_current.is_(True)))).scalars()) if body.result_ids else []
    if len(contribs) != len(set(body.contribution_ids)) or len(results) != len(set(body.result_ids)):
        raise unprocessable("unknown_reference", "a linked contribution or result does not belong to this project")
    assessed = {r.result_manifest_id for r in (await ctx.db.execute(select(ResultAssessmentRecord).where(
        ResultAssessmentRecord.result_manifest_id.in_([r.id for r in results]),
        ResultAssessmentRecord.is_current.is_(True)))).scalars()} if results else set()
    if any(r.protocol_id != frozen.id for r in results):
        raise unprocessable("result_protocol_mismatch", "attached results were produced under another protocol version")
    coverage = (await ctx.db.execute(select(LiteratureCoverageAssessment.id).where(
        LiteratureCoverageAssessment.project_id == project_id))).first() is not None
    content = {"description": body.description, **body.fields}
    ctxv = {"contributions": [str(c.id) for c in contribs],
            "results": [{"id": str(r.id), "assessed": r.id in assessed} for r in results], "coverage": coverage}
    vres = []
    for vid in stage.validator_ids:
        afn = ASYNC_VALIDATORS.get(vid)
        if afn is not None:
            ok, detail = await afn(ctx.db, project, frozen, content, ctxv)
            vres.append({"id": vid, "passed": bool(ok), "detail": detail})
            continue
        fn = VALIDATORS.get(vid)
        if fn is None:
            vres.append({"id": vid, "passed": False, "detail": "validator not implemented in this release (fail closed)"})
            continue
        ok, detail = fn(content, ctxv)
        vres.append({"id": vid, "passed": bool(ok), "detail": detail})
    status = "validated" if all(v["passed"] for v in vres) else "failed"
    deps = [frozen.artifact_id] + [c.artifact_id for c in contribs if c.artifact_id] + [r.artifact_id for r in results]
    pub = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "method_stage_output",
                                      {"stage": stage_id, "protocol_hash": frozen.content_hash, "content": content,
                                       "contributions": ctxv["contributions"], "results": ctxv["results"],
                                       "validators": vres}, depends_on=deps, label=f"Stage output: {stage.title}")).artifact
    for old in (await ctx.db.execute(select(MethodStageOutput).where(MethodStageOutput.protocol_id == frozen.id,
                                                                     MethodStageOutput.stage_id == stage_id,
                                                                     MethodStageOutput.is_current.is_(True)))).scalars():
        old.is_current = False
    out = MethodStageOutput(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id,
                            protocol_id=frozen.id, stage_id=stage_id, artifact_id=pub.id, content=content,
                            validator_results=vres, status=status, submitted_by=ctx.principal.actor_id)
    ctx.db.add(out)
    await ctx.db.flush()
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.ANALYSIS if stage_id in ("analysis", "evaluation")
                         else LedgerCategory.THEORETICAL_WORK if inst.study_type == "theoretical" else LedgerCategory.SUPPLIED_DATA,
                         f"Recorded method stage '{stage.title}'", source_action="method.stage", artifact_id=pub.id)
    transition = None
    if status == "validated" and project.state == ProjectState.RESEARCH_ACTIVE:
        g = await stages_complete(ctx.db, project)
        if g.passed:
            transition = (await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
                requested_state=ProjectState.OUTCOME_REVIEW, expected_project_version=project.version,
                idempotency_key=f"stages-complete:{frozen.id}:{out.id}", cause="request",
                method_definition_version=inst.definition_key, output_artifact_ids=[pub.id]))).as_dict()
    await ctx.db.commit()
    return {"stage_id": stage_id, "status": status, "validators": vres, "artifact_id": str(pub.id), "transition": transition}


@gate("method.required_stages_complete")
async def stages_complete(db: AsyncSession, project: Project) -> GateResult:
    inst = await active_instance(db, project.id)
    if inst is None:
        return GateResult("method.required_stages_complete", False, ["no method workflow selected"])
    frozen = await frozen_protocol(db, inst.id)
    if frozen is None:
        return GateResult("method.required_stages_complete", False, ["no frozen protocol"])
    outs = {o.stage_id: o for o in (await db.execute(select(MethodStageOutput).where(
        MethodStageOutput.protocol_id == frozen.id, MethodStageOutput.is_current.is_(True)))).scalars()}
    arts = {a.id: a for a in (await db.execute(select(Artifact).where(Artifact.id.in_([o.artifact_id for o in outs.values()])))).scalars()} if outs else {}
    reasons = []
    for s in definition_of(inst).required_stages:
        o = outs.get(s.id)
        if o is None:
            reasons.append(f"stage '{s.title}' has no output")
        elif o.status != "validated":
            reasons.append(f"stage '{s.title}' failed validation")
        elif arts.get(o.artifact_id) is None or arts[o.artifact_id].freshness != "current":
            reasons.append(f"stage '{s.title}' output is stale")
    return GateResult("method.required_stages_complete", not reasons, reasons,
                      evidence={"protocol_version": frozen.version_number, "definition": inst.definition_key})


# --------------------------------------------------------------------------- internal (methodology review)
@router.get("/internal/projects/{project_id}/protocols/{protocol_id}")
async def internal_protocol(project_id: uuid.UUID, protocol_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    p = (await ctx.db.execute(select(Protocol).where(Protocol.id == protocol_id, Protocol.project_id == project_id))).scalar_one_or_none()
    if p is None:
        raise not_found("protocol")
    inst = (await ctx.db.execute(select(MethodWorkflowInstance).where(MethodWorkflowInstance.id == p.method_instance_id))).scalar_one()
    direction = (await ctx.db.execute(select(Artifact).where(Artifact.project_id == project_id,
                                                             Artifact.kind == "research_direction",
                                                             Artifact.freshness == "current"))).scalars().first()
    dj = await art_svc.read_artifact_json(direction) if direction else {}
    return {**protocol_out(p), "definition": definition_of(inst).model_dump(),
            "research_question": dj.get("research_question"), "intended_contribution": dj.get("intended_contribution")}


class ReviewIn(BaseModel):
    status: str = Field(pattern="^(performed|not_performed)$")
    review: dict[str, Any] | None = None
    artifact_id: uuid.UUID | None = None
    reason: str | None = None


@router.post("/internal/projects/{project_id}/protocols/{protocol_id}/review")
async def internal_review(project_id: uuid.UUID, protocol_id: uuid.UUID, body: ReviewIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "methodology_review")
    p = (await ctx.db.execute(select(Protocol).where(Protocol.id == protocol_id, Protocol.project_id == project_id))).scalar_one_or_none()
    if p is None:
        raise not_found("protocol")
    if body.artifact_id:
        await art_svc.require_committed(ctx.db, [body.artifact_id], project_id)
    p.review_status = body.status
    p.review_artifact_id = body.artifact_id
    if body.review:
        issues = [dict(i) for i in body.review.get("issues", [])]
        for flag in body.review.get("ethics_flags", []):
            issues.append({"severity": "major", "section": "ethics_rights_declaration", "issue": flag,
                           "rationale": "ethics flag raised by the independent review", "proposed_fix": "address or justify"})
        p.review_issues = issues
    elif body.reason:
        p.review_issues = []
    await ctx.db.commit()
    return protocol_out(p)
