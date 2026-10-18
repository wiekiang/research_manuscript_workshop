"""M5 - original contribution workspace, supplied results with honest assurance, contribution validation matrix,
gap-resolution assessment and H3."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from rp_contracts.artifacts import ARTIFACT_KINDS
from rp_contracts.contribution import GAP_RESOLUTIONS, OUTCOMES, RESULT_ATTESTATION, MatrixRow, ResultManifest
from rp_contracts.copy import CONTRIBUTION_WORKSPACE_FIELDS, CONTRIBUTION_WORKSPACE_TITLE
from rp_contracts.enums import ClaimCategory, Gate, LedgerCategory, ProjectState
from rp_contracts.hashing import sha256_hex
from rp_contracts.scanning import scan

from ..db.base import utcnow
from ..db.models.contribution import (
    Contribution,
    ContributionValidationRow,
    GapResolutionAssessment,
    MethodStageOutput,
    ResultAssessmentRecord,
    ResultManifestRecord,
)
from ..db.models.core import Artifact
from ..db.models.literature import Claim, ClaimSupport, VerificationRecord
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import approvals as approval_svc
from ..services import artifacts as art_svc
from ..services import claims as claim_svc
from ..services import ledger
from ..services.approvals import DECLARATIONS
from ..services.common import audit
from ..services.tasks import create_task
from ..services.transitions import TransitionRequest, request_transition
from .method import active_instance, frozen_protocol

router = APIRouter(tags=["results"])
MAX_CONTRIB = 200 * 1024 * 1024
TYPES = {"dataset", "code", "notes", "annotations", "observations", "theoretical_argument", "interview_protocol",
         "results", "interpretation", "limitations", "methodological_decision", "other"}
LEDGER_FOR = {"dataset": LedgerCategory.SUPPLIED_DATA, "code": LedgerCategory.ANALYSIS, "results": LedgerCategory.ANALYSIS,
              "interpretation": LedgerCategory.INTERPRETATION, "theoretical_argument": LedgerCategory.THEORETICAL_WORK,
              "methodological_decision": LedgerCategory.METHODOLOGY_EDIT, "limitations": LedgerCategory.INTERPRETATION,
              "observations": LedgerCategory.SUPPLIED_DATA, "annotations": LedgerCategory.ANALYSIS}
EXT_TYPES = {"csv": "text/csv", "json": "application/json", "txt": "text/plain", "md": "text/markdown", "pdf": "application/pdf",
             "py": "text/x-python", "ipynb": "application/x-ipynb+json", "zip": "application/zip", "png": "image/png",
             "svg": "image/svg+xml", "tex": "text/x-tex"}


def contribution_out(c: Contribution) -> dict:
    return {"id": str(c.id), "user_id": str(c.user_id), "type": c.contribution_type, "workspace_field": c.workspace_field,
            "title": c.title, "text": c.text, "artifact_id": str(c.artifact_id) if c.artifact_id else None,
            "content_hash": c.content_hash, "license": c.license, "visibility": c.visibility,
            "pii_classification": c.pii_classification, "rights_statement": c.rights_statement,
            "relation_to_protocol": c.relation_to_protocol, "scan_report": c.scan_report, "created_at": c.created_at}


@router.get("/projects/{project_id}/contributions")
async def list_contributions(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(Contribution).where(Contribution.project_id == project_id)
                                 .order_by(Contribution.created_at))).scalars()
    return {"title": CONTRIBUTION_WORKSPACE_TITLE, "fields": CONTRIBUTION_WORKSPACE_FIELDS,
            "items": [contribution_out(c) for c in rows]}


@router.post("/projects/{project_id}/contributions", status_code=201)
async def add_contribution(
    project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), file: UploadFile | None = File(None),
    contribution_type: str = Form(...), title: str = Form(..., min_length=3, max_length=400),
    text: str | None = Form(None, max_length=200000), workspace_field: str | None = Form(None, max_length=60),
    license: str | None = Form(None, max_length=200), visibility: str = Form("private", pattern="^(public|private|restricted)$"),
    pii_classification: str = Form(..., pattern="^(none|pseudonymized|personal|sensitive)$"),
    rights_statement: str | None = Form(None, max_length=4000), relation_to_protocol: str | None = Form(None, max_length=4000),
):
    """Validated contribution (file type, size, malware scan, rights, PII class). Recorded in the ledger."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    if contribution_type not in TYPES:
        raise unprocessable("unknown_type", f"type must be one of {sorted(TYPES)}")
    if file is None and not (text and text.strip()):
        raise unprocessable("content_required", "attach a file or write the contribution")
    if file is not None and not rights_statement:
        raise unprocessable("rights_required", "state your right to use this file (origin, licence, consent)")
    art_id, digest, report = None, sha256_hex((text or "").encode()), {}
    if file is not None:
        data = await file.read(MAX_CONTRIB + 1)
        if len(data) > MAX_CONTRIB:
            raise unprocessable("file_too_large", "contribution files are limited to 200 MB")
        ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
        media = EXT_TYPES.get(ext)
        if media is None or media not in ARTIFACT_KINDS["contribution_file"].media_types:
            raise unprocessable("file_type_not_allowed", f".{ext} files are not accepted", {"allowed": sorted(EXT_TYPES)})
        rep = scan(data, media if media not in ("text/csv", "text/x-python", "text/markdown", "text/x-tex",
                                                "application/x-ipynb+json") else "text/plain")
        if rep.verdict == "rejected":
            raise unprocessable("file_rejected", "the file failed malware/quarantine scanning", rep.to_dict())
        report = rep.to_dict()
        classification = "restricted" if pii_classification in ("personal", "sensitive") or visibility == "restricted" \
            else "internal"
        pub = await art_svc.publish_bytes(ctx.db, ctx.principal, ctx.tenant_id, project_id, "contribution_file", data, media,
                                          label=f"{contribution_type}: {title}"[:300], classification=classification,
                                          rights={"license": license, "statement": rights_statement,
                                                  "pii": pii_classification,
                                                  "model_use": "prohibited" if classification == "restricted" else "owner_attestation_required"},
                                          metadata={"filename": file.filename, "scan": report})
        art_id, digest = pub.artifact.id, pub.artifact.content_hash
    frozen = None
    inst = await active_instance(ctx.db, project_id)
    if inst is not None:
        frozen = await frozen_protocol(ctx.db, inst.id)
    c = Contribution(tenant_id=ctx.tenant_id, project_id=project_id, user_id=ctx.principal.user_id,
                     contribution_type=contribution_type, workspace_field=workspace_field, title=title, text=text,
                     artifact_id=art_id, content_hash=digest, license=license, visibility=visibility,
                     pii_classification=pii_classification, rights_statement=rights_statement,
                     relation_to_protocol=relation_to_protocol, protocol_id=frozen.id if frozen else None, scan_report=report)
    ctx.db.add(c)
    await ctx.db.flush()
    await ledger.capture(ctx.db, ctx.principal, project, LEDGER_FOR.get(contribution_type, LedgerCategory.OTHER),
                         f"Contributed {contribution_type}: {title}", source_action="contribution.add", artifact_id=art_id,
                         rationale=text[:2000] if text and contribution_type in ("interpretation", "theoretical_argument",
                                                                                 "methodological_decision") else None)
    await ctx.db.commit()
    return contribution_out(c)


# --------------------------------------------------------------------------- results
def result_out(r: ResultManifestRecord, a: ResultAssessmentRecord | None = None) -> dict:
    return {"id": str(r.id), "result_key": r.result_key, "title": r.title, "manifest": r.manifest,
            "artifact_id": str(r.artifact_id), "origin": r.origin, "status": r.status, "assurance_level": r.assurance_level,
            "is_current": r.is_current, "created_at": r.created_at,
            "assessment": None if a is None else {
                "id": str(a.id), "assurance_level": a.assurance_level, "checks": a.checks, "missing": a.missing,
                "impossible_checks": a.impossible_checks, "wording_limits": a.wording_limits, "blockers": a.blockers,
                "assessor": a.assessor, "reviewer_note": a.reviewer_note, "artifact_id": str(a.artifact_id)}}


@router.post("/projects/{project_id}/results", status_code=201)
async def submit_result(project_id: uuid.UUID, body: ResultManifest, ctx: Ctx = Depends(user_ctx)):
    """Researcher-supplied result manifest; must be bound to the frozen protocol hash. Assessed deterministically."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    inst = await active_instance(ctx.db, project_id)
    frozen = await frozen_protocol(ctx.db, inst.id) if inst else None
    if frozen is None:
        raise unprocessable("h2_required", "results can be accepted only against an H2-frozen protocol")
    if body.protocol_hash != frozen.content_hash or body.protocol_version != frozen.version_number:
        raise unprocessable("protocol_mismatch", "the manifest must name the frozen protocol version and hash",
                            {"frozen_version": frozen.version_number, "frozen_hash": frozen.content_hash})
    if not body.attestation_accepted:
        raise unprocessable("attestation_required", "accept the result attestation", {"text": RESULT_ATTESTATION})
    file_ids = [uuid.UUID(f.artifact_id) for f in body.files]
    await art_svc.require_committed(ctx.db, file_ids, project_id)
    n = (await ctx.db.execute(select(func.count()).select_from(ResultManifestRecord).where(
        ResultManifestRecord.project_id == project_id))).scalar_one()
    key = f"RES-{n + 1:03d}"
    data = {**body.model_dump(mode="json"), "result_key": key, "attested_by": str(ctx.principal.user_id),
            "attestation_text": RESULT_ATTESTATION, "submitted_at": utcnow().isoformat()}
    pub = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "result_manifest", data,
                                      depends_on=[frozen.artifact_id, *file_ids], label=f"Result {key}: {body.title}"[:300])).artifact
    r = ResultManifestRecord(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id,
                             protocol_id=frozen.id, result_key=key, title=body.title, manifest=data, artifact_id=pub.id,
                             attested_by=ctx.principal.user_id)
    ctx.db.add(r)
    await ctx.db.flush()
    task, _ = await create_task(ctx.db, ctx.principal, project, "result_assessment", {"result_id": str(r.id)},
                                input_manifest={"result": pub.content_hash})
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.SUPPLIED_DATA,
                         f"Supplied result {key}: {body.title}", source_action="result.submit", artifact_id=pub.id,
                         rationale=body.methods[:2000], rationale_requested=False)
    await ctx.db.commit()
    return {**result_out(r), "task": task_out(task)}


@router.get("/projects/{project_id}/results")
async def list_results(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = list((await ctx.db.execute(select(ResultManifestRecord).where(ResultManifestRecord.project_id == project_id)
                                      .order_by(ResultManifestRecord.created_at))).scalars())
    out = []
    for r in rows:
        a = (await ctx.db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == r.id,
                                                                       ResultAssessmentRecord.is_current.is_(True)))).scalars().first()
        out.append(result_out(r, a))
    return {"items": out, "attestation_text": RESULT_ATTESTATION}


class AssessIn(BaseModel):
    result_id: uuid.UUID


@router.post("/projects/{project_id}/results/assess", status_code=202)
async def reassess_result(project_id: uuid.UUID, body: AssessIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    r = await _result(ctx, project_id, body.result_id)
    task, _ = await create_task(ctx.db, ctx.principal, project, "result_assessment", {"result_id": str(r.id)},
                                input_manifest={"result": str(r.artifact_id), "at": utcnow().isoformat()})
    await ctx.db.commit()
    return {"task": task_out(task)}


@router.get("/projects/{project_id}/results/{result_id}/assurance")
async def assurance(project_id: uuid.UUID, result_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    r = await _result(ctx, project_id, result_id)
    a = (await ctx.db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == r.id,
                                                                   ResultAssessmentRecord.is_current.is_(True)))).scalars().first()
    return result_out(r, a)


async def _result(ctx: Ctx, project_id, result_id) -> ResultManifestRecord:
    r = (await ctx.db.execute(select(ResultManifestRecord).where(ResultManifestRecord.id == result_id,
                                                                 ResultManifestRecord.project_id == project_id))).scalar_one_or_none()
    if r is None:
        raise not_found("result")
    return r


class ResultClaimIn(BaseModel):
    proposition: str = Field(min_length=5, max_length=4000)
    metric_name: str
    condition: str | None = None
    category: ClaimCategory = ClaimCategory.NUMERICAL
    researcher_confirms_match: bool = False


@router.post("/projects/{project_id}/results/{result_id}/claims", status_code=201)
async def result_claim(project_id: uuid.UUID, result_id: uuid.UUID, body: ResultClaimIn, ctx: Ctx = Depends(user_ctx)):
    """Observed-result claim linked to a committed result artifact; wording is limited by the assurance level."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    r = await _result(ctx, project_id, result_id)
    metric = next((m for m in r.manifest["metrics"] if m["name"] == body.metric_name
                   and (body.condition is None or m.get("condition") == body.condition)), None)
    if metric is None:
        raise unprocessable("unknown_metric", "the result manifest has no such metric")
    c = Claim(tenant_id=ctx.tenant_id, project_id=project_id, claim_key=await claim_svc.next_claim_key(ctx.db, project_id),
              proposition=body.proposition, normalized={"measure": metric["name"], "population_or_dataset": r.title,
                                                        "comparison": metric.get("condition"), "signature": sha256_hex(
                                                            f"{result_id}:{body.proposition}".encode())},
              kind="observed_result", category=body.category.value, critical=True, created_by=ctx.principal.actor_id,
              origin="researcher")
    ctx.db.add(c)
    await ctx.db.flush()
    s = ClaimSupport(tenant_id=ctx.tenant_id, claim_id=c.id, result_ref=f"{r.result_key}:{metric['name']}", relation="supports")
    ctx.db.add(s)
    await ctx.db.flush()
    ctx.db.add(VerificationRecord(tenant_id=ctx.tenant_id, project_id=project_id, claim_id=c.id, support_id=s.id,
                                  check="units", outcome="recorded" if metric.get("unit") else "missing",
                                  method="deterministic", verifier="result-manifest-units", verifier_version="1",
                                  evidence={"unit": metric.get("unit"), "n": metric.get("n")}))
    if body.researcher_confirms_match:
        ctx.db.add(VerificationRecord(tenant_id=ctx.tenant_id, project_id=project_id, claim_id=c.id, support_id=s.id,
                                      check="support", outcome="supports", method="human", verifier=ctx.principal.actor_id,
                                      verifier_version="ui-1", evidence={"result": r.result_key, "value": metric["value"]}))
    await claim_svc.reevaluate(ctx.db, ctx.principal, c)
    await ctx.db.commit()
    return {"claim_id": str(c.id), "claim_key": c.claim_key, "status": c.status, "decision": c.decision,
            "assurance_level": r.assurance_level, "wording_limits": (await _wording(ctx, r.id))}


async def _wording(ctx: Ctx, result_id) -> list[str]:
    a = (await ctx.db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == result_id,
                                                                   ResultAssessmentRecord.is_current.is_(True)))).scalars().first()
    return a.wording_limits if a else ["assessment pending: do not report this result yet"]


# --------------------------------------------------------------------------- contribution validation matrix
def row_out(r: ContributionValidationRow) -> dict:
    return {"id": str(r.id), "rq_index": r.rq_index, "research_question": r.research_question,
            "intended_novelty": r.intended_novelty, "intended_contribution": r.intended_contribution,
            "success_criterion": r.success_criterion, "evidence_ids": r.evidence_ids,
            "validity_assessment": r.validity_assessment, "outcome": r.outcome, "limitations": r.limitations,
            "h3_decision": r.h3_decision, "origin": r.origin, "version": r.row_version, "reviewed_at": r.reviewed_at}


@router.get("/projects/{project_id}/contribution-matrix")
async def contribution_matrix(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Rows per research question; drafts come from the H1 direction and committed results and require review."""
    project, _ = await project_for(ctx, project_id)
    inst = await active_instance(ctx.db, project_id)
    if inst is None:
        return {"items": [], "note": "select a method first"}
    rows = list((await ctx.db.execute(select(ContributionValidationRow).where(
        ContributionValidationRow.method_instance_id == inst.id, ContributionValidationRow.is_current.is_(True))
        .order_by(ContributionValidationRow.rq_index))).scalars())
    if not rows:
        direction = (await ctx.db.execute(select(Artifact).where(Artifact.project_id == project_id,
                                                                 Artifact.kind == "research_direction",
                                                                 Artifact.freshness == "current"))).scalars().first()
        if direction is not None:
            dj = await art_svc.read_artifact_json(direction)
            results = (await ctx.db.execute(select(ResultManifestRecord.result_key).where(
                ResultManifestRecord.method_instance_id == inst.id, ResultManifestRecord.is_current.is_(True)))).scalars().all()
            verified = (await ctx.db.execute(select(Claim.claim_key).where(
                Claim.project_id == project_id, Claim.status == "verified", Claim.kind == "observed_result"))).scalars().all()
            row = ContributionValidationRow(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id,
                                            rq_index=1, research_question=dj["research_question"],
                                            intended_novelty=dj.get("how_it_differs", ""),
                                            intended_contribution=dj["intended_contribution"],
                                            success_criterion=dj.get("success_criterion") or "",
                                            evidence_ids=list(results) + list(verified), origin="draft")
            ctx.db.add(row)
            await ctx.db.commit()
            rows = [row]
    gap = (await ctx.db.execute(select(GapResolutionAssessment).where(GapResolutionAssessment.method_instance_id == inst.id,
                                                                      GapResolutionAssessment.is_current.is_(True)))).scalars().first()
    return {"items": [row_out(r) for r in rows], "outcomes": OUTCOMES,
            "gap_resolution": None if gap is None else {"status": gap.status, "supporting_ids": gap.supporting_ids,
                                                        "explanation": gap.explanation, "at": gap.created_at},
            "note": "Draft rows are generated from verified artifacts and must be reviewed by the researcher. Demonstrated-"
                    "contribution language in the manuscript may use only H3-approved rows."}


class MatrixReviewIn(BaseModel):
    rows: list[MatrixRow]


@router.post("/projects/{project_id}/contribution-matrix/review")
async def review_matrix(project_id: uuid.UUID, body: MatrixReviewIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    inst = await active_instance(ctx.db, project_id)
    if inst is None:
        raise unprocessable("no_method", "select a method first")
    valid_ids = set((await ctx.db.execute(select(ResultManifestRecord.result_key).where(
        ResultManifestRecord.method_instance_id == inst.id, ResultManifestRecord.is_current.is_(True)))).scalars().all())
    valid_ids |= set((await ctx.db.execute(select(Claim.claim_key).where(Claim.project_id == project_id))).scalars().all())
    for row in body.rows:
        bad = [e for e in row.evidence_ids if e not in valid_ids]
        if bad:
            raise unprocessable("unknown_evidence", f"evidence ids not in this project: {bad}")
        if row.outcome is None or not (row.validity_assessment and row.validity_assessment.strip()):
            raise unprocessable("row_incomplete", f"RQ {row.rq_index}: record the outcome and your validity assessment")
        if row.outcome in ("supported", "partially_supported") and not row.evidence_ids:
            raise unprocessable("evidence_required", f"RQ {row.rq_index}: a supported outcome needs linked evidence")
    for old in (await ctx.db.execute(select(ContributionValidationRow).where(
            ContributionValidationRow.method_instance_id == inst.id, ContributionValidationRow.is_current.is_(True)))).scalars():
        old.is_current = False
    new_rows = []
    for row in body.rows:
        r = ContributionValidationRow(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id,
                                      **row.model_dump(), origin="researcher_reviewed", reviewed_by=ctx.principal.user_id,
                                      reviewed_at=utcnow())
        ctx.db.add(r)
        new_rows.append(r)
    await ctx.db.flush()
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION,
                         "Reviewed the contribution validation matrix", source_action="matrix.review",
                         rationale="; ".join(f"RQ{r.rq_index}: {r.outcome} - {r.validity_assessment}" for r in body.rows)[:4000],
                         rationale_requested=False)
    await ctx.db.commit()
    return {"items": [row_out(r) for r in new_rows]}


class GapIn(BaseModel):
    status: str
    supporting_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=20, max_length=8000)


@router.post("/projects/{project_id}/gap-resolution")
async def gap_resolution(project_id: uuid.UUID, body: GapIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    if body.status not in GAP_RESOLUTIONS:
        raise unprocessable("invalid_status", f"choose one of {GAP_RESOLUTIONS}")
    inst = await active_instance(ctx.db, project_id)
    rows = list((await ctx.db.execute(select(ContributionValidationRow).where(
        ContributionValidationRow.method_instance_id == inst.id, ContributionValidationRow.is_current.is_(True)))).scalars())
    if not rows or any(r.origin != "researcher_reviewed" for r in rows):
        raise unprocessable("rows_not_reviewed", "review every contribution-matrix row before the overall assessment")
    outcomes = {r.outcome for r in rows}
    if body.status == "addressed" and outcomes - {"supported"}:
        raise unprocessable("overstated", "the gap cannot be 'addressed' while some research questions are not supported")
    if body.status == "addressed" and "inconclusive" in outcomes:
        raise unprocessable("overstated", "an inconclusive study cannot claim the gap was filled")
    for old in (await ctx.db.execute(select(GapResolutionAssessment).where(GapResolutionAssessment.method_instance_id == inst.id,
                                                                           GapResolutionAssessment.is_current.is_(True)))).scalars():
        old.is_current = False
    g = GapResolutionAssessment(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id, status=body.status,
                                supporting_ids=body.supporting_ids, explanation=body.explanation,
                                assessed_by=ctx.principal.user_id)
    ctx.db.add(g)
    await ctx.db.flush()
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION,
                         f"Assessed gap resolution: {body.status}", source_action="gap.assess", rationale=body.explanation,
                         rationale_requested=False)
    await ctx.db.commit()
    return {"status": g.status, "explanation": g.explanation}


class H3In(BaseModel):
    interpretation: str = Field(min_length=40, max_length=20000)
    limitations: str = Field(min_length=20, max_length=20000)
    anomalies_reviewed: bool
    declaration_accepted: bool
    declaration_text: str


@router.post("/projects/{project_id}/results/approve")
async def approve_results(project_id: uuid.UUID, body: H3In, ctx: Ctx = Depends(user_ctx)):
    """H3: the researcher validates actual outcomes, interpretation and limitations."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    if project.state != ProjectState.OUTCOME_REVIEW:
        raise conflict("wrong_state", f"H3 is recorded in OUTCOME_REVIEW (project is {project.state})")
    inst = await active_instance(ctx.db, project_id)
    reasons = []
    if not body.anomalies_reviewed:
        reasons.append("confirm that anomalies, statistics and assurance levels were reviewed")
    results = list((await ctx.db.execute(select(ResultManifestRecord).where(
        ResultManifestRecord.method_instance_id == inst.id, ResultManifestRecord.is_current.is_(True)))).scalars())
    assessments = []
    for r in results:
        a = (await ctx.db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == r.id,
                                                                       ResultAssessmentRecord.is_current.is_(True)))).scalars().first()
        if a is None:
            reasons.append(f"{r.result_key} has not been assessed")
        elif a.blockers:
            reasons.append(f"{r.result_key}: {'; '.join(a.blockers)}")
        else:
            assessments.append(a)
    rows = list((await ctx.db.execute(select(ContributionValidationRow).where(
        ContributionValidationRow.method_instance_id == inst.id, ContributionValidationRow.is_current.is_(True)))).scalars())
    if not rows or any(r.origin != "researcher_reviewed" for r in rows):
        reasons.append("review every contribution-matrix row")
    gap = (await ctx.db.execute(select(GapResolutionAssessment).where(GapResolutionAssessment.method_instance_id == inst.id,
                                                                      GapResolutionAssessment.is_current.is_(True)))).scalars().first()
    if gap is None:
        reasons.append("record whether the work addressed the proposed gap")
    if reasons:
        raise ApiError(422, "gate_unsatisfied", "H3 preconditions are not met", {"reasons": reasons})
    matrix = {"rows": [row_out(r) for r in rows], "gap_resolution": {"status": gap.status, "explanation": gap.explanation,
                                                                     "supporting_ids": gap.supporting_ids},
              "interpretation": body.interpretation, "limitations": body.limitations,
              "assurance": {r.result_key: r.assurance_level for r in results}}
    stage_arts = [o.artifact_id for o in (await ctx.db.execute(select(MethodStageOutput).where(
        MethodStageOutput.method_instance_id == inst.id, MethodStageOutput.is_current.is_(True)))).scalars()]
    deps = [r.artifact_id for r in results] + [a.artifact_id for a in assessments] + stage_arts
    m_art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "contribution_matrix", matrix,
                                        depends_on=deps, label="Contribution validation matrix (H3)")).artifact
    gap.artifact_id = m_art.id
    bound = [m_art] + [await art_svc.get_artifact(ctx.db, i, project_id) for i in deps]
    appr = await approval_svc.record_approval(ctx.db, ctx.principal, project, Gate.H3, bound,
                                              declaration_accepted=body.declaration_accepted,
                                              declaration_text=body.declaration_text, rationale=body.interpretation)
    for r in rows:
        r.h3_decision = r.h3_decision or "accepted"
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION, "Validated outcomes at H3",
                         source_action="results.approve", rationale=f"{body.interpretation}\n\nLimitations: {body.limitations}",
                         rationale_requested=False, artifact_id=m_art.id)
    res = await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
        requested_state=ProjectState.DRAFTING, expected_project_version=project.version, idempotency_key=f"h3:{appr.id}",
        human_approval_id=appr.id, cause="approval", method_definition_version=inst.definition_key))
    await ctx.db.commit()
    return {"approval_id": str(appr.id), "matrix_artifact_id": str(m_art.id), "transition": res.as_dict(),
            "declaration": DECLARATIONS[Gate.H3].text}


# --------------------------------------------------------------------------- internal (assessment worker)
@router.get("/internal/projects/{project_id}/results/{result_id}")
async def internal_result(project_id: uuid.UUID, result_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    r = await _result(ctx, project_id, result_id)
    frozen = await frozen_protocol(ctx.db, r.method_instance_id)
    return {**result_out(r), "frozen_protocol_hash": frozen.content_hash if frozen else None}


class AssessmentIn(BaseModel):
    artifact_id: uuid.UUID
    assessment: dict[str, Any]
    assessor: str


@router.post("/internal/projects/{project_id}/results/{result_id}/assessment")
async def record_assessment(project_id: uuid.UUID, result_id: uuid.UUID, body: AssessmentIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "result_assessment", "experiment_recompute")
    r = await _result(ctx, project_id, result_id)
    await art_svc.require_committed(ctx.db, [body.artifact_id], project_id)
    a = body.assessment
    for old in (await ctx.db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == r.id,
                                                                          ResultAssessmentRecord.is_current.is_(True)))).scalars():
        old.is_current = False
    rec = ResultAssessmentRecord(tenant_id=ctx.tenant_id, result_manifest_id=r.id, artifact_id=body.artifact_id,
                                 assurance_level=a["level"], checks=a["checks"], missing=a["missing"],
                                 impossible_checks=a["impossible_checks"], wording_limits=a["wording_limits"],
                                 blockers=a["blockers"], assessor=body.assessor)
    ctx.db.add(rec)
    r.assurance_level = a["level"]
    r.status = "assessed"
    await audit(ctx.db, ctx.principal, "result.assessed", project_id=project_id, resource_type="result",
                resource_id=r.id, details={"level": a["level"], "blockers": a["blockers"]})
    await ctx.db.commit()
    return result_out(r, rec)


_ = OUTCOMES
