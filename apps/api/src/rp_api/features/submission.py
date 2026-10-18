"""M8 - author records and assent, disclosures and AI-use policy, deadline policy evaluator, Submission Readiness
Assessment, H4 sign-off of a frozen content manifest, and version-locked package build/verification.

The platform never submits to a venue. Export is possible before H4 for author review, visibly marked unapproved.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import Gate, LedgerCategory, ProjectState
from rp_contracts.hashing import content_hash
from rp_contracts.latexdoc import Author
from rp_contracts.manuscript import section_text
from rp_contracts.submission import (
    AUTHOR_APPROVAL_TEXT,
    EVALUATOR_VERSION,
    OFFLINE_ATTESTATION_TEXT,
    READINESS_VERSION,
    UNAPPROVED_NOTICE,
    AuthorIn,
    DeadlineIn,
    DisclosuresIn,
    author_problems,
    evaluate_deadlines,
    readiness_stage,
)

from ..db.base import utcnow
from ..db.models.cfp import CfpRule, DeadlineObligation
from ..db.models.core import Approval, ApprovalDependency, Artifact, Project, ProjectMember
from ..db.models.latex import CompileRun
from ..db.models.literature import LiteratureCoverageAssessment
from ..db.models.manuscript import BibliographyEntry, Manuscript, ManuscriptSpan, ManuscriptVersion
from ..db.models.review import IntegrityReport, ReviewFinding, ReviewReport, ReviewRound
from ..db.models.submission import (
    AuthorAssent,
    AuthorEntry,
    DisclosureRecord,
    EligibilityAssessment,
    ExportPackage,
    ReadinessAssessment,
)
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, forbidden, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import approvals as approval_svc
from ..services import artifacts as art_svc
from ..services import gates as gate_svc
from ..services import invalidation, ledger
from ..services.gates import GateResult, gate
from ..services.tasks import create_task
from ..services.transitions import TransitionRequest, request_transition
from ..storage import get_store
from .method import active_instance, definition_of
from .review import current_version, latest_round

router = APIRouter(tags=["submission"])
gate("h4.approved")(approval_svc._approval_gate(Gate.H4))
PRE_APPROVAL_GATES = ("manuscript.complete", "review.passed", "compliance.checked", "integrity.checked")


def now_utc() -> datetime:
    return datetime.now(UTC)


async def _supersede(db: AsyncSession, actor, project: Project, old_artifact_ids: list[uuid.UUID], reason: str, key: str):
    """A changed author record/disclosure invalidates whatever bound the previous version (e.g. H4, packages)."""
    if old_artifact_ids:
        await invalidation.invalidate(db, actor, project, old_artifact_ids, reason, key)


# --------------------------------------------------------------------------- authors
async def current_authors(db: AsyncSession, project_id: uuid.UUID) -> list[AuthorEntry]:
    return list((await db.execute(select(AuthorEntry).where(AuthorEntry.project_id == project_id, AuthorEntry.is_current.is_(True))
                                  .order_by(AuthorEntry.position))).scalars())


async def author_list(db: AsyncSession, project_id: uuid.UUID) -> list[Author]:
    """Author block for the identified (camera-ready / non-anonymous) rendering."""
    return [Author(name=a.name, email=a.email, affiliation="; ".join(a.affiliations) or None, orcid=a.orcid)
            for a in await current_authors(db, project_id)]


async def assents_for(db: AsyncSession, authors: list[AuthorEntry], version_id: uuid.UUID | None) -> dict[uuid.UUID, AuthorAssent]:
    if not authors or version_id is None:
        return {}
    rows = (await db.execute(select(AuthorAssent).where(AuthorAssent.author_entry_id.in_([a.id for a in authors]),
                                                        AuthorAssent.manuscript_version_id == version_id))).scalars()
    return {r.author_entry_id: r for r in rows}


def author_out(a: AuthorEntry, assent: AuthorAssent | None) -> dict:
    return {"id": str(a.id), "position": a.position, "name": a.name, "email": a.email, "affiliations": a.affiliations,
            "orcid": a.orcid, "user_id": str(a.user_id) if a.user_id else None, "corresponding": a.corresponding,
            "contribution_roles": a.contribution_roles, "contribution_statement": a.contribution_statement,
            "competing_interests": a.competing_interests, "funding": a.funding, "record_version": a.record_version,
            "assent": ({"method": assent.method, "at": assent.created_at, "evidence": assent.evidence,
                        "recorded_by": str(assent.recorded_by)} if assent else None)}


class AuthorsIn(BaseModel):
    expected_record_version: int
    authors: list[AuthorIn]


@router.get("/projects/{project_id}/authors")
async def get_authors(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    authors = await current_authors(ctx.db, project_id)
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.project_id == project_id))).scalar_one_or_none()
    assents = await assents_for(ctx.db, authors, m.current_version_id if m else None)
    return {"record_version": authors[0].record_version if authors else 0,
            "authors": [author_out(a, assents.get(a.id)) for a in authors],
            "manuscript_version": m.current_version_number if m else None,
            "author_approval_text": AUTHOR_APPROVAL_TEXT, "offline_attestation_text": OFFLINE_ATTESTATION_TEXT,
            "note": "The contribution log is evidence for author review, never an authorship certification."}


@router.put("/projects/{project_id}/authors")
async def put_authors(project_id: uuid.UUID, body: AuthorsIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    old = await current_authors(ctx.db, project_id)
    current_version_no = old[0].record_version if old else 0
    if body.expected_record_version != current_version_no:
        raise conflict("stale_version", "the author record changed; reload", {"record_version": current_version_no})
    problems = author_problems(body.authors)
    members = {str(m.user_id): m for m in (await ctx.db.execute(select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.removed_at.is_(None)))).scalars()}
    for a in body.authors:
        if a.user_id and a.user_id not in members:
            problems.append(f"{a.name}: linked user is not a project member")
    if problems:
        raise ApiError(422, "invalid_authors", "the author record is incomplete", {"problems": problems})
    n = current_version_no + 1
    record = {"version": n, "authors": [a.model_dump() for a in body.authors]}
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "author_record", record,
                                      label=f"Author record v{n}")).artifact
    for a in old:
        a.is_current = False
    for i, a in enumerate(body.authors, start=1):
        ctx.db.add(AuthorEntry(tenant_id=ctx.tenant_id, project_id=project_id, record_version=n, position=i, name=a.name,
                               email=a.email, affiliations=a.affiliations, orcid=a.orcid,
                               user_id=uuid.UUID(a.user_id) if a.user_id else None, corresponding=a.corresponding,
                               contribution_roles=a.contribution_roles, contribution_statement=a.contribution_statement,
                               competing_interests=a.competing_interests, funding=a.funding, artifact_id=art.id))
    # The corresponding author signs H4: keep the member flag in sync with the author record.
    corr = next((a for a in body.authors if a.corresponding), None)
    for uid, m in members.items():
        m.is_corresponding_author = bool(corr and corr.user_id == uid)
    await _supersede(ctx.db, ctx.principal, project, list({a.artifact_id for a in old}), f"author record changed (v{n})",
                     f"authors:{art.id}")
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.OTHER, f"Updated the author record (v{n})",
                         source_action="authors.update", artifact_id=art.id, rationale_requested=False)
    await ctx.db.commit()
    return await get_authors(project_id, ctx)


class AssentIn(BaseModel):
    statement_accepted: bool
    statement_text: str
    evidence: str | None = Field(default=None, max_length=4000)
    evidence_artifact_id: uuid.UUID | None = None


@router.post("/projects/{project_id}/authors/{author_id}/approve", status_code=201)
async def author_approve(project_id: uuid.UUID, author_id: uuid.UUID, body: AssentIn, ctx: Ctx = Depends(user_ctx)):
    """In-product approval by the author themself, or an offline attestation recorded by the corresponding author."""
    project, role = await project_for(ctx, project_id)
    a = (await ctx.db.execute(select(AuthorEntry).where(AuthorEntry.id == author_id, AuthorEntry.project_id == project_id,
                                                        AuthorEntry.is_current.is_(True)))).scalar_one_or_none()
    if a is None:
        raise not_found("author")
    _, v, _ = await current_version(ctx.db, project_id)
    if a.user_id == ctx.principal.user_id:
        method, text = "in_product", AUTHOR_APPROVAL_TEXT
    else:
        me = (await ctx.db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                               ProjectMember.user_id == ctx.principal.user_id))).scalar_one()
        if not me.is_corresponding_author:
            raise forbidden("only the author, or the corresponding author recording an offline attestation, can do this")
        if not (body.evidence or body.evidence_artifact_id):
            raise unprocessable("evidence_required", "describe or attach the author's explicit approval")
        if body.evidence_artifact_id:
            await art_svc.require_committed(ctx.db, [body.evidence_artifact_id], project_id)
        method, text = "offline_attestation", OFFLINE_ATTESTATION_TEXT
    if not body.statement_accepted or body.statement_text != text:
        raise unprocessable("statement_mismatch", "accept the exact statement", {"statement": text})
    ctx.db.add(AuthorAssent(tenant_id=ctx.tenant_id, project_id=project_id, author_entry_id=a.id, manuscript_version_id=v.id,
                            manuscript_hash=v.content_hash, method=method, statement=text, evidence=body.evidence,
                            evidence_artifact_id=body.evidence_artifact_id, recorded_by=ctx.principal.user_id))
    await ctx.db.commit()
    return {"author_id": str(a.id), "method": method, "manuscript_version": v.version_number}


# --------------------------------------------------------------------------- disclosures and AI policy
async def current_disclosure(db: AsyncSession, project_id: uuid.UUID) -> DisclosureRecord | None:
    return (await db.execute(select(DisclosureRecord).where(DisclosureRecord.project_id == project_id,
                                                            DisclosureRecord.is_current.is_(True)))).scalar_one_or_none()


async def declarations_for(db: AsyncSession, project_id: uuid.UUID) -> dict | None:
    """Used by the integrity engine; None until disclosures are recorded."""
    d = await current_disclosure(db, project_id)
    return dict(d.data) if d else None


@router.get("/projects/{project_id}/disclosures")
async def get_disclosures(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    d = await current_disclosure(ctx.db, project_id)
    venue_policy = None
    if project.target_edition_id:
        r = (await ctx.db.execute(select(CfpRule).where(CfpRule.edition_id == project.target_edition_id,
                                                        CfpRule.rule_key == "ai_policy.statement",
                                                        CfpRule.is_current.is_(True)))).scalars().first()
        if r:
            venue_policy = {"quote": r.quote, "rule_id": str(r.id), "status": r.status}
    ai_spans = 0
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.project_id == project_id))).scalar_one_or_none()
    if m and m.current_version_id:
        ai_spans = (await ctx.db.execute(select(func.count()).select_from(ManuscriptSpan).where(
            ManuscriptSpan.version_id == m.current_version_id, ManuscriptSpan.origin == "ai"))).scalar_one()
    return {"disclosures": d.data if d else None, "record_version": d.record_version if d else 0,
            "venue_ai_policy_from_cfp": venue_policy, "ai_drafted_spans": ai_spans,
            "guidance": "Consult the current publisher and track policy on AI assistance, where disclosure goes and "
                        "whether the use is permitted. Venues can be stricter than publishers. Paste the policy text "
                        "as published and record your interpretation."}


class DisclosurePut(BaseModel):
    expected_record_version: int
    disclosures: DisclosuresIn


@router.put("/projects/{project_id}/disclosures")
async def put_disclosures(project_id: uuid.UUID, body: DisclosurePut, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES, lock=True)
    old = await current_disclosure(ctx.db, project_id)
    n0 = old.record_version if old else 0
    if body.expected_record_version != n0:
        raise conflict("stale_version", "the disclosures changed; reload", {"record_version": n0})
    data = body.disclosures.model_dump()
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "disclosure_statement",
                                      {"version": n0 + 1, **data}, label=f"Disclosure statement v{n0 + 1}")).artifact
    if old:
        old.is_current = False
    ctx.db.add(DisclosureRecord(tenant_id=ctx.tenant_id, project_id=project_id, record_version=n0 + 1, data=data,
                                artifact_id=art.id, recorded_by=ctx.principal.user_id))
    await _supersede(ctx.db, ctx.principal, project, [old.artifact_id] if old else [], "disclosures changed",
                     f"disclosures:{art.id}")
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.OTHER, "Recorded disclosures and AI-use policy",
                         source_action="disclosures.update", artifact_id=art.id, rationale=data["ai_policy_interpretation"])
    await ctx.db.commit()
    return await get_disclosures(project_id, ctx)


# --------------------------------------------------------------------------- deadline policy evaluator
async def _deadlines(db: AsyncSession, project: Project) -> list[DeadlineIn]:
    if not project.target_edition_id:
        return []
    rows = (await db.execute(select(DeadlineObligation).where(
        DeadlineObligation.edition_id == project.target_edition_id, DeadlineObligation.is_current.is_(True),
        (DeadlineObligation.track_id.is_(None)) | (DeadlineObligation.track_id == project.target_track_id)))).scalars()
    return [DeadlineIn(id=str(d.id), kind=d.deadline_kind, due_at=d.due_at, timezone=d.stated_timezone,
                       governs=d.governs_actions or [], mandatory=d.mandatory, applicability=d.applicability,
                       status=d.status, prerequisite_for=d.prerequisite_for or []) for d in rows]


class EligibilityIn(BaseModel):
    intended_action: str = Field(default="new_submission")
    completed_prerequisites: list[dict[str, str]] = Field(
        default_factory=list, description="[{kind, reference}] e.g. the abstract registration ID; a human attestation")


@router.post("/projects/{project_id}/eligibility", status_code=201)
async def assess_eligibility(project_id: uuid.UUID, body: EligibilityIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    for p in body.completed_prerequisites:
        if not p.get("kind") or len(p.get("reference", "")) < 3:
            raise unprocessable("reference_required", "record the confirmation/reference of each completed prerequisite")
    res = evaluate_deadlines(await _deadlines(ctx.db, project), body.intended_action, now_utc(),
                             {p["kind"] for p in body.completed_prerequisites})
    sched = (await ctx.db.execute(select(Artifact).where(Artifact.project_id == project_id, Artifact.kind == "deadline_schedule",
                                                         Artifact.freshness == "current")
                                  .order_by(Artifact.created_at.desc()))).scalars().first()
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "eligibility_assessment",
                                      {**res.model_dump(mode="json"), "completed_prerequisites": body.completed_prerequisites},
                                      depends_on=[sched.id] if sched else None,
                                      label=f"Eligibility for {body.intended_action}")).artifact
    row = EligibilityAssessment(tenant_id=ctx.tenant_id, project_id=project_id, action=body.intended_action, status=res.status,
                                result=res.model_dump(mode="json"), completed_prerequisites=body.completed_prerequisites,
                                schedule_artifact_id=sched.id if sched else None, artifact_id=art.id,
                                evaluator_version=EVALUATOR_VERSION, assessed_by=ctx.principal.actor_id)
    ctx.db.add(row)
    await ctx.db.commit()
    return {"id": str(row.id), **res.model_dump(mode="json")}


async def latest_eligibility(db: AsyncSession, project_id: uuid.UUID, action: str = "new_submission") -> EligibilityAssessment | None:
    return (await db.execute(select(EligibilityAssessment).where(EligibilityAssessment.project_id == project_id,
                                                                 EligibilityAssessment.action == action)
                             .order_by(EligibilityAssessment.created_at.desc()))).scalars().first()


@router.get("/projects/{project_id}/eligibility")
async def get_eligibility(project_id: uuid.UUID, action: str = "new_submission", ctx: Ctx = Depends(user_ctx)):
    """Latest recorded assessment plus a live re-evaluation (a deadline may have passed since it was recorded)."""
    project, _ = await project_for(ctx, project_id)
    e = await latest_eligibility(ctx.db, project_id, action)
    live = evaluate_deadlines(await _deadlines(ctx.db, project), action, now_utc(),
                              {p["kind"] for p in (e.completed_prerequisites if e else [])})
    return {"recorded": ({"id": str(e.id), **e.result, "completed_prerequisites": e.completed_prerequisites,
                          "artifact_id": str(e.artifact_id), "assessed_by": e.assessed_by} if e else None),
            "live": live.model_dump(mode="json")}


@gate("eligibility.current")
async def eligibility_current(db: AsyncSession, project: Project) -> GateResult:
    e = await latest_eligibility(db, project.id)
    if e is None:
        return GateResult("eligibility.current", False, ["assess submission eligibility for a new submission"])
    art = (await db.execute(select(Artifact).where(Artifact.id == e.artifact_id))).scalar_one()
    reasons = []
    if art.freshness != "current":
        reasons.append(f"the eligibility assessment is stale ({art.stale_reason}); re-assess")
    # Re-evaluate at gate time: a deadline may have passed since the assessment was recorded.
    res = evaluate_deadlines(await _deadlines(db, project), e.action, now_utc(), {p["kind"] for p in e.completed_prerequisites})
    if res.status != "eligible":
        reasons += res.reasons or [f"eligibility is {res.status}"]
    return GateResult("eligibility.current", not reasons, reasons, evidence={"assessment": str(e.id)})


# --------------------------------------------------------------------------- readiness assessment
async def _gate_map(db: AsyncSession, project: Project, ids) -> dict[str, GateResult]:
    return {g: await gate_svc.evaluate(db, project, g) for g in ids}


@router.post("/projects/{project_id}/readiness", status_code=201)
async def assess_readiness(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Versioned Submission Readiness Assessment; never hides outstanding manual checks."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    gm = await _gate_map(ctx.db, project, PRE_APPROVAL_GATES + ("h4.approved", "package.verified", "eligibility.current"))
    try:
        _, v, content = await current_version(ctx.db, project_id)
    except ApiError:
        v = content = None
    deps, hashes = [], {}
    if v:
        deps.append(v.artifact_id)
        hashes["manuscript"] = v.content_hash
        for f in ("scientific", "citation_evidence", "technical", "compliance"):
            r = await latest_round(ctx.db, project_id, v.id, f)
            if r:
                rep = (await ctx.db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id,
                                                                       ReviewReport.function == f))).scalar_one()
                deps.append(rep.artifact_id)
                hashes[f"review:{f}"] = str(rep.artifact_id)
        ir = (await ctx.db.execute(select(IntegrityReport).where(IntegrityReport.project_id == project_id,
                                                                 IntegrityReport.manuscript_version_id == v.id,
                                                                 IntegrityReport.status == "complete")
                                   .order_by(IntegrityReport.created_at.desc()))).scalars().first()
        if ir and ir.artifact_id:
            deps.append(ir.artifact_id)
            hashes["integrity"] = str(ir.artifact_id)
    manual = []
    if v:
        r = await latest_round(ctx.db, project_id, v.id, "compliance")
        if r:
            rep = (await ctx.db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id,
                                                                   ReviewReport.function == "compliance"))).scalar_one()
            manual = [{"id": c["id"], "detail": c["detail"], "source": c.get("source")}
                      for c in rep.summary.get("checks", []) if c["status"] == "manual_check"]
    limitations = []
    cov = (await ctx.db.execute(select(LiteratureCoverageAssessment).where(LiteratureCoverageAssessment.project_id == project_id)
                                .order_by(LiteratureCoverageAssessment.created_at.desc()))).scalars().first()
    if cov:
        limitations.append(f"Literature coverage: {cov.message}")
    if content is not None:
        abstract = section_text(content.section("abstract"))
        limitations.append(f"Manuscript v{v.version_number}; abstract {len(abstract.split())} words")
    gates = {k: g.passed for k, g in gm.items()}
    pkg_ok, elig_ok = gates.pop("package.verified"), gates.pop("eligibility.current")
    stage = readiness_stage(project.state, gates, pkg_ok, elig_ok)
    checks = [{"gate": k, "passed": g.passed, "reasons": g.reasons} for k, g in gm.items()]
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "readiness_assessment",
                                      {"stage": stage, "checks": checks, "manual_checks": manual, "limitations": limitations,
                                       "source_hashes": hashes, "assessor": ctx.principal.actor_id,
                                       "assessor_version": READINESS_VERSION, "assessed_at": now_utc().isoformat()},
                                      depends_on=deps or None, label=f"Submission readiness ({stage})")).artifact
    row = ReadinessAssessment(tenant_id=ctx.tenant_id, project_id=project_id, manuscript_version_id=v.id if v else None,
                              stage=stage, checks=checks, manual_checks=manual, limitations=limitations, source_hashes=hashes,
                              artifact_id=art.id, assessor=ctx.principal.actor_id, assessor_version=READINESS_VERSION)
    ctx.db.add(row)
    await ctx.db.commit()
    return readiness_out(row)


def readiness_out(r: ReadinessAssessment) -> dict:
    return {"id": str(r.id), "stage": r.stage, "checks": r.checks, "manual_checks": r.manual_checks,
            "limitations": r.limitations, "source_hashes": r.source_hashes, "artifact_id": str(r.artifact_id),
            "assessor": r.assessor, "assessor_version": r.assessor_version, "created_at": r.created_at}


@router.get("/projects/{project_id}/readiness")
async def get_readiness(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(ReadinessAssessment).where(ReadinessAssessment.project_id == project_id)
                                 .order_by(ReadinessAssessment.created_at.desc()).limit(10))).scalars()
    gm = await _gate_map(ctx.db, project, PRE_APPROVAL_GATES + ("h4.approved", "package.verified", "eligibility.current"))
    gates = {k: g.passed for k, g in gm.items()}
    live = readiness_stage(project.state, gates, gates.pop("package.verified"), gates.pop("eligibility.current"))
    return {"current_stage": live, "gates": {k: g.as_dict() for k, g in gm.items()},
            "items": [readiness_out(r) for r in rows],
            "notice": "The platform does not submit to any venue. PACKAGE_READY means ready for human export."}


@gate("readiness.pre_approval")
async def readiness_pre_approval(db: AsyncSession, project: Project) -> GateResult:
    try:
        _, v, _ = await current_version(db, project.id)
    except ApiError:
        return GateResult("readiness.pre_approval", False, ["no manuscript"])
    r = (await db.execute(select(ReadinessAssessment).where(ReadinessAssessment.project_id == project.id,
                                                            ReadinessAssessment.manuscript_version_id == v.id)
                          .order_by(ReadinessAssessment.created_at.desc()))).scalars().first()
    if r is None:
        return GateResult("readiness.pre_approval", False, ["record the pre-approval readiness assessment"])
    reasons = []
    art = (await db.execute(select(Artifact).where(Artifact.id == r.artifact_id))).scalar_one()
    if art.freshness != "current":
        reasons.append(f"the readiness assessment is stale ({art.stale_reason})")
    if r.stage not in ("compliance_checked", "approved_for_export", "submission_ready_package"):
        reasons.append(f"the assessment recorded stage {r.stage}; compliance_checked is required")
    for g in PRE_APPROVAL_GATES:
        res = await gate_svc.evaluate(db, project, g)
        if not res.passed:
            reasons.append(f"{g} no longer passes")
    return GateResult("readiness.pre_approval", not reasons, reasons, evidence={"assessment": str(r.id)})


# --------------------------------------------------------------------------- final gates
@gate("method.enabled_for_submission")
async def method_enabled(db: AsyncSession, project: Project) -> GateResult:
    inst = await active_instance(db, project.id)
    if inst is None:
        return GateResult("method.enabled_for_submission", False, ["no method selected"])
    d = definition_of(inst)
    if not (inst.enabled_for_submission_ready and d.enabled_for_submission_ready):
        return GateResult("method.enabled_for_submission", False,
                          [f"{d.title} is planning-only: {d.planning_only_reason}"])
    return GateResult("method.enabled_for_submission", True)


@gate("contribution.recorded")
async def contribution_recorded(db: AsyncSession, project: Project) -> GateResult:
    ok = await ledger.has_substantive_contribution(db, project.id)
    return GateResult("contribution.recorded", ok, [] if ok else ["no substantive human contribution is recorded"])


@gate("blockers.none")
async def blockers_none(db: AsyncSession, project: Project) -> GateResult:
    reasons = []
    try:
        _, v, _ = await current_version(db, project.id)
    except ApiError:
        return GateResult("blockers.none", False, ["no manuscript"])
    rounds = (await db.execute(select(ReviewRound.id).where(ReviewRound.manuscript_version_id == v.id))).scalars().all()
    n = (await db.execute(select(func.count()).select_from(ReviewFinding).where(
        ReviewFinding.round_id.in_(rounds), ReviewFinding.status == "open", ReviewFinding.severity == "blocker"))).scalar_one() if rounds else 0
    if n:
        reasons.append(f"{n} open blocker finding(s)")
    spans = (await db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == v.id))).scalars()
    if any(i["severity"] == "blocker" for s in spans for i in s.issues):
        reasons.append("manuscript spans have blocking issues")
    if not await current_authors(db, project.id):
        reasons.append("no author record")
    if await current_disclosure(db, project.id) is None:
        reasons.append("no disclosure statement")
    return GateResult("blockers.none", not reasons, reasons)


# --------------------------------------------------------------------------- content manifest and H4
async def _pdf_run(db: AsyncSession, project: Project, v: ManuscriptVersion) -> CompileRun | None:
    anon_rule = None
    if project.target_edition_id:
        anon_rule = (await db.execute(select(CfpRule).where(CfpRule.edition_id == project.target_edition_id,
                                                            CfpRule.rule_key == "anonymization.mode",
                                                            CfpRule.is_current.is_(True)))).scalars().first()
    want_anon = bool(anon_rule and (anon_rule.value or "").lower() in ("double_blind", "double-blind", "anonymous"))
    runs = (await db.execute(select(CompileRun).where(CompileRun.project_id == project.id, CompileRun.kind == "manuscript",
                                                      CompileRun.manuscript_version_id == v.id, CompileRun.status == "compiled")
                             .order_by(CompileRun.created_at.desc()))).scalars()
    return next((r for r in runs if bool((r.options or {}).get("anonymous")) == want_anon), None)


async def content_items(db: AsyncSession, actor, project: Project) -> tuple[list[dict], list[str]]:
    """Everything H4 signs: exact committed artifacts. Returns (items, problems)."""
    problems: list[str] = []
    _, v, content = await current_version(db, project.id)
    items = [{"role": "manuscript", "path": "manuscript/manuscript.json", "artifact_id": v.artifact_id}]
    run = await _pdf_run(db, project, v)
    if run is None or run.pdf_artifact_id is None:
        problems.append("compile the current version in the venue's required (anonymized/identified) mode")
    else:
        items.append({"role": "pdf", "path": "paper.pdf", "artifact_id": run.pdf_artifact_id})
        if run.source_bundle_artifact_id:
            items.append({"role": "source", "path": "source/latex-source.zip", "artifact_id": run.source_bundle_artifact_id})
    bib = list((await db.execute(select(BibliographyEntry).where(BibliographyEntry.project_id == project.id,
                                                                 BibliographyEntry.is_current.is_(True))
                                 .order_by(BibliographyEntry.cite_key))).scalars())
    bib_art = (await art_svc.publish_bytes(db, actor, project.tenant_id, project.id, "bibliography",
                                           "\n".join(b.bibtex for b in bib).encode(), "application/x-bibtex",
                                           label="Bibliography (verified identities)")).artifact
    items.append({"role": "bibliography", "path": "references.bib", "artifact_id": bib_art.id})
    for s in content.sections:
        for f in s.figures:
            items.append({"role": "figure", "path": f"figures/{f.file_name}", "artifact_id": uuid.UUID(f.artifact_id)})
    authors = await current_authors(db, project.id)
    if authors:
        items.append({"role": "author_record", "path": "authors.json", "artifact_id": authors[0].artifact_id})
    else:
        problems.append("record the authors")
    d = await current_disclosure(db, project.id)
    if d:
        items.append({"role": "disclosures", "path": "disclosures.json", "artifact_id": d.artifact_id})
    else:
        problems.append("record the disclosures")
    r = await latest_round(db, project.id, v.id, "compliance")
    if r:
        rep = (await db.execute(select(ReviewReport).where(ReviewReport.round_id == r.id,
                                                           ReviewReport.function == "compliance"))).scalar_one()
        items.append({"role": "compliance_report", "path": "reports/compliance.json", "artifact_id": rep.artifact_id})
    ir = (await db.execute(select(IntegrityReport).where(IntegrityReport.project_id == project.id,
                                                         IntegrityReport.manuscript_version_id == v.id,
                                                         IntegrityReport.status == "complete")
                           .order_by(IntegrityReport.created_at.desc()))).scalars().first()
    if ir and ir.artifact_id:
        items.append({"role": "integrity_report", "path": "reports/integrity.json", "artifact_id": ir.artifact_id})
    ra = (await db.execute(select(ReadinessAssessment).where(ReadinessAssessment.project_id == project.id,
                                                             ReadinessAssessment.manuscript_version_id == v.id)
                           .order_by(ReadinessAssessment.created_at.desc()))).scalars().first()
    if ra:
        items.append({"role": "readiness_assessment", "path": "reports/readiness.json", "artifact_id": ra.artifact_id})
    arts = {a.id: a for a in (await db.execute(select(Artifact).where(Artifact.id.in_([i["artifact_id"] for i in items])))).scalars()}
    out = []
    for i in items:
        a = arts.get(i["artifact_id"])
        if a is None:
            problems.append(f"{i['role']} artifact missing")
            continue
        out.append({**i, "artifact_id": str(a.id), "kind": a.kind, "sha256": a.content_hash, "media_type": a.media_type})
    return out, problems


@router.get("/projects/{project_id}/content-manifest")
async def preview_manifest(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    items, problems = await content_items(ctx.db, ctx.principal, project)
    _, v, _ = await current_version(ctx.db, project_id)
    authors = await current_authors(ctx.db, project_id)
    assents = await assents_for(ctx.db, authors, v.id)
    missing = [a.name for a in authors if a.id not in assents]
    await ctx.db.commit()
    return {"items": items, "problems": problems, "manuscript_version": v.version_number,
            "authors_without_approval": missing, "declaration": approval_svc.DECLARATIONS[Gate.H4].text}


class FinalIn(BaseModel):
    declaration_accepted: bool
    declaration_text: str
    rationale: str | None = Field(default=None, max_length=4000)


@router.post("/projects/{project_id}/final-approval")
async def final_approval(project_id: uuid.UUID, body: FinalIn, ctx: Ctx = Depends(user_ctx)):
    """H4: the corresponding author signs the frozen content manifest after the pre-approval assessment."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES, lock=True)
    if project.state != ProjectState.FINAL_APPROVAL:
        raise conflict("wrong_state", f"H4 is signed in FINAL_APPROVAL (project is {project.state})")
    reasons = []
    pre = await gate_svc.evaluate(ctx.db, project, "readiness.pre_approval")
    reasons += pre.reasons
    items, problems = await content_items(ctx.db, ctx.principal, project)
    reasons += problems
    _, v, _ = await current_version(ctx.db, project_id)
    authors = await current_authors(ctx.db, project_id)
    assents = await assents_for(ctx.db, authors, v.id)
    reasons += [f"{a.name} has not approved manuscript v{v.version_number}" for a in authors if a.id not in assents]
    if reasons:
        raise ApiError(422, "gate_unsatisfied", "H4 preconditions are not met", {"reasons": reasons})
    manifest = {"manuscript_version": v.version_number, "items": items, "assents": [
        {"author": a.name, "method": assents[a.id].method, "manuscript_hash": assents[a.id].manuscript_hash} for a in authors]}
    cm = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "content_manifest", manifest,
                                     depends_on=[uuid.UUID(i["artifact_id"]) for i in items],
                                     label=f"Content manifest (v{v.version_number})")).artifact
    bound = [cm] + [await art_svc.get_artifact(ctx.db, uuid.UUID(i["artifact_id"]), project_id) for i in items]
    appr = await approval_svc.record_approval(ctx.db, ctx.principal, project, Gate.H4, bound,
                                              declaration_accepted=body.declaration_accepted,
                                              declaration_text=body.declaration_text, rationale=body.rationale)
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.MANUSCRIPT_CHANGE, "Signed H4 final approval",
                         source_action="h4.approve", artifact_id=cm.id, rationale=body.rationale, rationale_requested=False)
    res = await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
        requested_state=ProjectState.APPROVED_FOR_EXPORT, expected_project_version=project.version,
        idempotency_key=f"h4:{appr.id}", human_approval_id=appr.id, cause="approval"))
    await ctx.db.commit()
    return {"approval_id": str(appr.id), "content_manifest_artifact_id": str(cm.id),
            "content_manifest_hash": appr.content_manifest_hash, "transition": res.as_dict()}


async def on_manuscript_version(db: AsyncSession, actor, project: Project, prev_artifact_id: uuid.UUID, reason: str) -> None:
    """Called when a new manuscript version is committed: anything that bound the previous version (H4, packages,
    reviews of that version) becomes stale. Typographical edits never reopen H1-H3."""
    bound = (await db.execute(select(ApprovalDependency.approval_id).join(Approval, Approval.id == ApprovalDependency.approval_id)
                              .where(ApprovalDependency.artifact_id == prev_artifact_id, Approval.status == "valid"))).first()
    if bound is not None:
        await invalidation.invalidate(db, actor, project, [prev_artifact_id], reason, f"msver:{prev_artifact_id}",
                                      mark_roots_stale=False)


# --------------------------------------------------------------------------- packages
class PackageIn(BaseModel):
    supplementary_artifact_ids: list[uuid.UUID] = Field(default_factory=list)


@router.post("/projects/{project_id}/packages", status_code=202)
async def build_package(project_id: uuid.UUID, body: PackageIn, ctx: Ctx = Depends(user_ctx)):
    """Version-locked package. Before H4 it is built for author review and visibly marked unapproved."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    appr, problems = await approval_svc.current_approval(ctx.db, project_id, Gate.H4)
    approved = appr is not None and not problems
    if approved:
        cm = next(b for b in appr.bound_artifacts if b.get("kind") == "content_manifest")
        cm_art = await art_svc.get_artifact(ctx.db, uuid.UUID(cm["id"]), project_id)
        items = (await art_svc.read_artifact_json(cm_art))["items"]
    else:
        cm_art = None
        items, missing = await content_items(ctx.db, ctx.principal, project)
        if not any(i["role"] == "manuscript" for i in items):
            raise unprocessable("nothing_to_package", "; ".join(missing))
    if body.supplementary_artifact_ids:
        for a in await art_svc.require_committed(ctx.db, body.supplementary_artifact_ids, project_id):
            items.append({"role": "supplementary", "path": f"supplementary/{a.id}", "artifact_id": str(a.id),
                          "kind": a.kind, "sha256": a.content_hash, "media_type": a.media_type})
    authors = await current_authors(ctx.db, project_id)
    _, v, content = await current_version(ctx.db, project_id)
    meta = {"title": content.title, "abstract": section_text(content.section("abstract")), "keywords": content.keywords,
            "authors": [{"name": a.name, "affiliations": a.affiliations, "email": a.email, "corresponding": a.corresponding}
                        for a in authors], "manuscript_version": v.version_number,
            "target": {"edition_id": str(project.target_edition_id) if project.target_edition_id else None,
                       "track_id": str(project.target_track_id) if project.target_track_id else None}}
    ra = (await ctx.db.execute(select(ReadinessAssessment).where(ReadinessAssessment.project_id == project_id)
                               .order_by(ReadinessAssessment.created_at.desc()))).scalars().first()
    checklist = ["# Submission checklist", "", "This package is prepared for human export. The platform does not submit it.", ""]
    for c in (ra.checks if ra else []):
        checklist.append(f"- [{'x' if c['passed'] else ' '}] {c['gate']}" + (f": {'; '.join(c['reasons'])}" if c["reasons"] else ""))
    for mc in (ra.manual_checks if ra else []):
        checklist.append(f"- [ ] manual: {mc['id']} - {mc['detail']}")
    readme = (f"Package for manuscript v{v.version_number}.\n\n"
              + (f"Approved at H4 (approval {appr.id}); content manifest hash {appr.content_manifest_hash}.\n" if approved
                 else UNAPPROVED_NOTICE + "\n"))
    n = (await ctx.db.execute(select(func.count()).select_from(ExportPackage).where(ExportPackage.project_id == project_id))).scalar_one()
    spec = {"approved": approved, "items": items, "inline": {"metadata.json": json.dumps(meta, indent=2, sort_keys=True),
                                                             "checklist.md": "\n".join(checklist) + "\n", "README.txt": readme},
            "content_manifest_hash": appr.content_manifest_hash if approved else None,
            "name": f"package-v{v.version_number}-{'approved' if approved else 'UNAPPROVED'}-{n + 1}.zip"}
    pkg_id = uuid.uuid4()
    task, _ = await create_task(ctx.db, ctx.principal, project, "package_build", {"package_id": str(pkg_id)},
                                input_manifest={"spec": content_hash(spec), "n": n})
    ctx.db.add(ExportPackage(id=pkg_id, tenant_id=ctx.tenant_id, project_id=project_id, task_id=task.id, approved=approved,
                             h4_approval_id=appr.id if approved else None,
                             content_manifest_artifact_id=cm_art.id if cm_art else None,
                             content_manifest_hash=spec["content_manifest_hash"], spec=spec))
    await ctx.db.commit()
    return {"task": task_out(task), "package_id": str(pkg_id), "approved": approved,
            "label": "approved" if approved else "unapproved"}


async def package_out(db: AsyncSession, p: ExportPackage) -> dict:
    stale = None
    if p.artifact_id:
        a = (await db.execute(select(Artifact).where(Artifact.id == p.artifact_id))).scalar_one_or_none()
        stale = a.stale_reason if a and a.freshness != "current" else None
    if p.approved and p.h4_approval_id:
        appr = (await db.execute(select(Approval).where(Approval.id == p.h4_approval_id))).scalar_one()
        if appr.status != "valid":
            stale = stale or f"H4 is {appr.status}: {appr.invalidation_reason or 'superseded'}"
    return {"id": str(p.id), "status": p.status, "approved": p.approved, "label": "approved" if p.approved else "unapproved",
            "artifact_id": str(p.artifact_id) if p.artifact_id else None, "checksum": p.checksum,
            "content_manifest_hash": p.content_manifest_hash, "problems": p.problems, "verified_at": p.verified_at,
            "created_at": p.created_at, "name": p.spec.get("name"), "stale": stale,
            "files": [{"path": f["path"], "sha256": f["sha256"]} for f in (p.manifest or {}).get("files", [])]}


@router.get("/projects/{project_id}/packages")
async def list_packages(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(ExportPackage).where(ExportPackage.project_id == project_id)
                                 .order_by(ExportPackage.created_at.desc()))).scalars()
    return {"items": [await package_out(ctx.db, p) for p in rows],
            "notice": "Exports are for human submission through the venue's own system; nothing is submitted for you."}


@gate("package.verified")
async def package_verified(db: AsyncSession, project: Project) -> GateResult:
    appr, problems = await approval_svc.current_approval(db, project.id, Gate.H4)
    if appr is None or problems:
        return GateResult("package.verified", False, ["no current H4 approval"] + problems)
    p = (await db.execute(select(ExportPackage).where(ExportPackage.project_id == project.id,
                                                      ExportPackage.h4_approval_id == appr.id,
                                                      ExportPackage.status == "verified")
                          .order_by(ExportPackage.created_at.desc()))).scalars().first()
    if p is None:
        return GateResult("package.verified", False, ["build and verify a package from the H4 content manifest"])
    a = (await db.execute(select(Artifact).where(Artifact.id == p.artifact_id))).scalar_one()
    if a.freshness != "current":
        return GateResult("package.verified", False, [f"the package is stale ({a.stale_reason})"])
    return GateResult("package.verified", True, evidence={"package": str(p.id), "checksum": p.checksum})


@router.get("/internal/packages/{package_id}/spec")
async def package_spec(package_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_task_kind(ctx, "package_build")
    p = (await ctx.db.execute(select(ExportPackage).where(ExportPackage.id == package_id))).scalar_one_or_none()
    if p is None:
        raise not_found("package")
    require_service_scope(ctx, p.project_id, "domain.read")
    return {"id": str(p.id), **p.spec}


class PackageResultIn(BaseModel):
    artifact_id: uuid.UUID
    manifest: dict[str, Any]


def verify_package(data: bytes, spec: dict) -> tuple[list[str], dict[str, str]]:
    """Recompute every member hash from the package bytes and compare with the signed content hashes."""
    problems, seen = [], {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            seen[info.filename] = hashlib.sha256(z.read(info)).hexdigest()
        manifest = json.loads(z.read("provenance-manifest.json")) if "provenance-manifest.json" in seen else None
    if manifest is None:
        problems.append("provenance manifest missing")
    for item in spec["items"]:
        got = seen.get(item["path"])
        if got is None:
            problems.append(f"{item['path']} missing from the package")
        elif got != item["sha256"]:
            problems.append(f"{item['path']} differs from the approved content hash")
    if manifest and spec.get("content_manifest_hash") and manifest.get("content_manifest_hash") != spec["content_manifest_hash"]:
        problems.append("the package manifest names a different content manifest")
    return problems, seen


@router.post("/internal/packages/{package_id}")
async def record_package(package_id: uuid.UUID, body: PackageResultIn, ctx: Ctx = Depends(service_ctx)):
    require_task_kind(ctx, "package_build")
    p = (await ctx.db.execute(select(ExportPackage).where(ExportPackage.id == package_id).with_for_update())).scalar_one_or_none()
    if p is None:
        raise not_found("package")
    require_service_scope(ctx, p.project_id, "domain.write")
    if p.status in ("verified", "built", "failed"):
        return await package_out(ctx.db, p)
    art = (await art_svc.require_committed(ctx.db, [body.artifact_id], p.project_id))[0]
    data = await art_svc.read_artifact_bytes(art)
    problems, _ = verify_package(data, p.spec)
    p.artifact_id, p.checksum, p.manifest, p.problems = art.id, art.content_hash, body.manifest, problems
    if problems:
        p.status = "failed"
    elif p.approved:
        p.status, p.verified_at = "verified", utcnow()
    else:
        p.status = "built"
    if p.content_manifest_artifact_id:
        await invalidation.link(ctx.db, art.tenant_id, p.content_manifest_artifact_id, art.id, "packaged_from")
    await ctx.db.flush()
    transition = None
    project = (await ctx.db.execute(select(Project).where(Project.id == p.project_id))).scalar_one()
    if p.status == "verified" and project.state == ProjectState.APPROVED_FOR_EXPORT:
        try:
            transition = (await request_transition(ctx.db, ctx.principal, p.project_id, TransitionRequest(
                requested_state=ProjectState.PACKAGE_READY, expected_project_version=project.version,
                idempotency_key=f"package:{p.id}", output_artifact_ids=[art.id], cause="request"))).as_dict()
        except ApiError as exc:
            transition = {"refused": exc.code, "details": exc.details}
    await ctx.db.commit()
    return {**await package_out(ctx.db, p), "transition": transition}


_ = (get_store, Field)
