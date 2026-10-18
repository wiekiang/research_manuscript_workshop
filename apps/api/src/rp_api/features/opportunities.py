"""M4 - gap proposals, nearest prior work, novelty caveats, advisory study-type and venue-category recommendations,
Paper Rationale ("Why this paper?") and feasibility. These are proposals only: H1 is completed in M5."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from rp_contracts import methods
from rp_contracts.enums import LedgerCategory
from rp_contracts.ranking import embed

from ..db.base import utcnow
from ..db.models.cfp import CfpRule, DeadlineObligation, Track
from ..db.models.literature import (
    EvidencePassage,
    FeasibilityAssessment,
    Opportunity,
    PaperRationale,
    StudyTypeRecommendation,
    TenantPaperRecord,
)
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import artifacts as art_svc
from ..services import budget as budget_svc
from ..services import ledger
from ..services.tasks import create_task

router = APIRouter(tags=["opportunities"])


@router.post("/projects/{project_id}/opportunities/generate", status_code=202)
async def generate(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    n = len((await ctx.db.execute(select(TenantPaperRecord.id).where(TenantPaperRecord.project_id == project_id))).all())
    if n < 3:
        raise unprocessable("insufficient_literature", "search for or add at least three papers before proposing research gaps")
    task, _ = await create_task(ctx.db, ctx.principal, project, "opportunity_generation", {},
                                input_manifest={"project": str(project_id), "papers": n, "at": utcnow().isoformat()})
    await ctx.db.commit()
    return {"task": task_out(task)}


def _direction_state(project) -> str:
    return "awaiting_H1" if project.state == "DIRECTION_REVIEW" else "direction_proposed"


@router.get("/projects/{project_id}/opportunities")
async def list_opportunities(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    ops = list((await ctx.db.execute(select(Opportunity).where(Opportunity.project_id == project_id,
                                                               Opportunity.is_current.is_(True))
                                     .order_by(Opportunity.position))).scalars())
    out = []
    for o in ops:
        rat = (await ctx.db.execute(select(PaperRationale).where(PaperRationale.opportunity_id == o.id,
                                                                 PaperRationale.is_current.is_(True)))).scalars().first()
        recs = list((await ctx.db.execute(select(StudyTypeRecommendation).where(
            StudyTypeRecommendation.opportunity_id == o.id))).scalars())
        feas = (await ctx.db.execute(select(FeasibilityAssessment).where(FeasibilityAssessment.opportunity_id == o.id,
                                                                         FeasibilityAssessment.is_current.is_(True)))).scalars().first()
        out.append({
            "id": str(o.id), "position": o.position, "title": o.title, "research_question": o.research_question,
            "details": o.details, "closest_work": o.closest_work, "novelty_caveat": o.novelty_caveat, "status": o.status,
            "provenance": o.provenance,
            "rationale": rationale_out(rat) if rat else None,
            "study_types": [rec_out(r) for r in recs],
            "feasibility": feas_out(feas) if feas else None,
        })
    return {"direction_state": _direction_state(project), "items": out,
            "note": "Proposals are advisory. Novelty is a hypothesis supported by the documented search, not a verified "
                    "property. The research direction is decided by the researcher at H1."}


def rationale_out(r: PaperRationale) -> dict:
    return {"id": str(r.id), "version": r.rationale_version, "problem": r.problem, "gap": r.gap,
            "gap_evidence": r.gap_evidence, "importance_to_venue": r.importance_to_venue,
            "research_question": r.research_question, "intended_contribution": r.intended_contribution,
            "success_criterion": r.success_criterion, "status": r.status,
            "artifact_id": str(r.artifact_id) if r.artifact_id else None,
            "label": "Proposed contribution (not a claim that the gap has been filled)"}


def rec_out(r: StudyTypeRecommendation) -> dict:
    return {"id": str(r.id), "study_type": r.study_type, "venue_category": r.venue_category,
            "fit_rationale": r.fit_rationale, "track_accepts": r.track_accepts, "track_rule_ref": r.track_rule_ref,
            "required_inputs": r.required_inputs, "reporting_standard": r.reporting_standard, "blockers": r.blockers,
            "method_enabled": r.method_enabled, "method_availability": r.method_availability, "advisory": r.advisory}


def feas_out(f: FeasibilityAssessment) -> dict:
    return {"id": str(f.id), "version": f.assessment_version, "deadlines": f.deadlines, "estimates": f.estimates,
            "cost_estimate": f.cost_estimate, "constraints": f.constraints, "assumptions": f.assumptions,
            "status": f.status, "uncertainty": f.uncertainty, "slack_days": f.slack_days,
            "note": "Advisory. A model estimate alone never blocks the project; you may proceed with a recorded rationale."}


class RationaleEdit(BaseModel):
    problem: str | None = Field(default=None, max_length=8000)
    gap: str | None = Field(default=None, max_length=8000)
    importance_to_venue: str | None = Field(default=None, max_length=8000)
    research_question: str | None = Field(default=None, max_length=4000)
    intended_contribution: str | None = Field(default=None, max_length=8000)
    success_criterion: str | None = Field(default=None, max_length=4000)


@router.patch("/projects/{project_id}/rationales/{rationale_id}")
async def edit_rationale(project_id: uuid.UUID, rationale_id: uuid.UUID, body: RationaleEdit, ctx: Ctx = Depends(user_ctx)):
    """Researcher edits create a new rationale version (the agent draft is preserved) and a ledger entry."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    old = (await ctx.db.execute(select(PaperRationale).where(PaperRationale.id == rationale_id,
                                                             PaperRationale.project_id == project_id))).scalar_one_or_none()
    if old is None:
        raise not_found("rationale")
    changes = {k: v for k, v in body.model_dump().items() if v is not None and v != getattr(old, k)}
    if not changes:
        return rationale_out(old)
    new = PaperRationale(tenant_id=old.tenant_id, project_id=project_id, opportunity_id=old.opportunity_id,
                         rationale_version=old.rationale_version + 1,
                         **{k: changes.get(k, getattr(old, k)) for k in ("problem", "gap", "importance_to_venue",
                                                                         "research_question", "intended_contribution",
                                                                         "success_criterion")},
                         gap_evidence=old.gap_evidence, status="researcher_edited", edited_by=ctx.principal.user_id)
    pub = await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "paper_rationale",
                                     {**rationale_out(new), "opportunity_id": str(old.opportunity_id)},
                                     label=f"Paper Rationale v{new.rationale_version}")
    new.artifact_id = pub.artifact.id
    old.is_current = False
    ctx.db.add(new)
    diff = "\n".join(ledger.text_diff(getattr(old, k), v, k) or "" for k, v in changes.items())
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.QUESTION_REFINEMENT,
                         f"Edited the Paper Rationale ({', '.join(changes)})", source_action="rationale.edit", diff=diff)
    await ctx.db.commit()
    return rationale_out(new)


@router.get("/projects/{project_id}/study-types")
async def study_types(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    recs = list((await ctx.db.execute(select(StudyTypeRecommendation).where(
        StudyTypeRecommendation.project_id == project_id))).scalars())
    return {"taxonomy": [{"study_type": d.study_type, "title": d.title, "definition": d.plain_definition,
                         "enabled_for_submission_ready": d.enabled_for_submission_ready, "availability": d.availability,
                         "planning_only_reason": d.planning_only_reason, "reporting_standard": d.reporting_standard,
                         "definition_version": d.definition_version}
                        for d in {x.study_type: methods.latest(x.study_type) for x in methods.DEFINITIONS}.values()],
            "venue_categories": methods.VENUE_CATEGORIES, "recommendations": [rec_out(r) for r in recs],
            "note": "Study type (what kind of research) and venue category (what kind of submission) are separate choices."}


@router.get("/projects/{project_id}/feasibility")
async def feasibility(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(FeasibilityAssessment).where(FeasibilityAssessment.project_id == project_id,
                                                                     FeasibilityAssessment.is_current.is_(True)))).scalars()
    return {"items": [feas_out(f) for f in rows]}


# --------------------------------------------------------------------------- internal
@router.get("/internal/projects/{project_id}/opportunity-inputs")
async def opportunity_inputs(project_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    """Inputs for the gap agent, restricted by item rights: publisher-copyright abstracts and passages from papers
    whose licence forbids model use are withheld (their metadata still counts as closest-work candidates)."""
    require_service_scope(ctx, project_id, "domain.read")
    require_task_kind(ctx, "opportunity_generation")
    project, _ = await project_for(ctx, project_id)
    papers = list((await ctx.db.execute(select(TenantPaperRecord).where(TenantPaperRecord.project_id == project_id))).scalars())
    passages = list((await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.project_id == project_id,
                                                                        EvidencePassage.verified_in_source.is_(True)))).scalars())
    model_ok = {p.id for p in papers if (p.rights or {}).get("model_use_permitted")}
    topics, tracks = None, []
    if project.target_edition_id:
        t = (await ctx.db.execute(select(CfpRule).where(CfpRule.edition_id == project.target_edition_id,
                                                        CfpRule.rule_key == "topics.list", CfpRule.is_current.is_(True)))).scalars().first()
        topics = t.value_text if t else None
        tr = list((await ctx.db.execute(select(Track).where(Track.edition_id == project.target_edition_id))).scalars())
        tracks = [{"name": x.name, "paper_types": x.paper_types, "categories": x.submission_categories} for x in tr]
    return {
        "project": {"title": project.title, "topic": project.topic, "description": project.description},
        "cfp": {"topics": topics, "tracks": tracks, "target_track_id": str(project.target_track_id) if project.target_track_id else None},
        "papers": [{"id": str(p.id), "title": p.title, "year": p.year, "venue": p.venue, "doi": p.doi,
                    "identity_status": p.identity_status,
                    "abstract": p.abstract if (p.abstract_rights == "cc_by_openaire_metadata" or p.id in model_ok) else None}
                   for p in papers],
        "passages": [{"id": str(x.id), "paper_id": str(x.paper_id), "quote": x.quote, "role": x.role}
                     for x in passages if x.paper_id in model_ok],
        "study_types": [{"study_type": d.study_type, "title": d.title, "enabled": d.enabled_for_submission_ready}
                        for d in methods.DEFINITIONS],
        "venue_categories": list(methods.VENUE_CATEGORIES),
    }


class OpportunitiesIn(BaseModel):
    set_artifact_id: uuid.UUID
    proposals: list[dict[str, Any]]
    negative_findings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


def _accepts(track: Track | None, category: str) -> tuple[str, dict]:
    if track is None:
        return "unknown", {"reason": "no target track selected"}
    listed = [x.lower() for x in (track.submission_categories or []) + (track.paper_types or [])]
    if not listed:
        return "unknown", {"reason": "the CFP does not list accepted paper types for this track"}
    key = category.replace("_", " ").split()[0]
    return ("yes" if any(key in x for x in listed) else "no"), {"track": track.name, "listed": listed}


@router.post("/internal/projects/{project_id}/opportunities")
async def store_opportunities(project_id: uuid.UUID, body: OpportunitiesIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "opportunity_generation")
    project, _ = await project_for(ctx, project_id)
    task_id = uuid.UUID(ctx.principal.scope["task_id"])
    if (await ctx.db.execute(select(Opportunity).where(Opportunity.task_id == task_id))).first():
        return {"replayed": True}
    await art_svc.require_committed(ctx.db, [body.set_artifact_id], project_id)
    papers = {str(p.id): p for p in (await ctx.db.execute(select(TenantPaperRecord).where(
        TenantPaperRecord.project_id == project_id))).scalars()}
    passages = {str(x.id): x for x in (await ctx.db.execute(select(EvidencePassage).where(
        EvidencePassage.project_id == project_id))).scalars()}
    track = (await ctx.db.execute(select(Track).where(Track.id == project.target_track_id))).scalar_one_or_none() \
        if project.target_track_id else None
    dls = list((await ctx.db.execute(select(DeadlineObligation).where(
        DeadlineObligation.edition_id == project.target_edition_id, DeadlineObligation.is_current.is_(True)))).scalars()) \
        if project.target_edition_id else []
    budget = await budget_svc.status(ctx.db, project)
    for old in (await ctx.db.execute(select(Opportunity).where(Opportunity.project_id == project_id,
                                                               Opportunity.is_current.is_(True)))).scalars():
        old.is_current = False
    problems: list[str] = []
    stored = 0
    for i, prop in enumerate(body.proposals, start=1):
        closest = [pid for pid in prop.get("closest_work_paper_ids", []) if pid in papers]
        if len(closest) != len(prop.get("closest_work_paper_ids", [])):
            problems.append(f"proposal {i}: dropped closest-work ids that are not project papers")
        if not closest:
            # nearest known work by embedding similarity as a deterministic fallback
            from ..db.models.literature import TenantPaperRecord as T

            q = embed(prop.get("research_question", "") + " " + prop.get("title", ""))
            near = (await ctx.db.execute(select(T).where(T.project_id == project_id, T.embedding.is_not(None))
                                         .order_by(T.embedding.cosine_distance(q)).limit(3))).scalars().all()
            closest = [str(p.id) for p in near]
        o = Opportunity(tenant_id=ctx.tenant_id, project_id=project_id, task_id=task_id, set_artifact_id=body.set_artifact_id,
                        position=i, title=prop["title"], research_question=prop["research_question"],
                        details={k: prop.get(k) for k in ("cfp_alignment", "potential_contribution", "how_it_differs",
                                                          "boundary_conditions", "data_availability", "compute_estimate",
                                                          "ethics_constraints", "threats_to_novelty")},
                        closest_work=[{"paper_id": pid, "title": papers[pid].title, "year": papers[pid].year,
                                       "doi": papers[pid].doi, "identity_status": papers[pid].identity_status}
                                      for pid in closest],
                        novelty_caveat=prop.get("novelty_caveat") or "Novelty is a hypothesis pending researcher review.",
                        provenance=body.provenance)
        ctx.db.add(o)
        await ctx.db.flush()
        rat = prop.get("rationale") or {}
        ev = [pid for pid in rat.get("gap_evidence_passage_ids", []) if pid in passages]
        if len(ev) != len(rat.get("gap_evidence_passage_ids", [])):
            problems.append(f"proposal {i}: dropped gap-evidence ids that are not verified project passages")
        r = PaperRationale(tenant_id=ctx.tenant_id, project_id=project_id, opportunity_id=o.id,
                           problem=rat.get("problem", ""), gap=rat.get("gap", ""),
                           gap_evidence=[{"passage_id": pid, "quote": passages[pid].quote, "paper_id": str(passages[pid].paper_id)}
                                         for pid in ev],
                           importance_to_venue=rat.get("importance_to_venue", ""), research_question=prop["research_question"],
                           intended_contribution=rat.get("intended_contribution", ""),
                           success_criterion=rat.get("success_criterion", ""), status="draft")
        ctx.db.add(r)
        await ctx.db.flush()
        pub = await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "paper_rationale",
                                         {**rationale_out(r), "opportunity_id": str(o.id)}, label=f"Paper Rationale (draft {i})",
                                         depends_on=[body.set_artifact_id])
        r.artifact_id = pub.artifact.id
        for st in prop.get("study_types", []):
            try:
                d = methods.latest(st.get("study_type", ""))
            except KeyError:
                problems.append(f"proposal {i}: unknown study type {st.get('study_type')!r} dropped")
                continue
            cat = st.get("venue_category") if st.get("venue_category") in methods.VENUE_CATEGORIES else "other"
            acc, ref = _accepts(track, cat)
            blockers = list(st.get("blockers") or [])
            if not d.enabled_for_submission_ready:
                blockers.append(f"planning only: {d.planning_only_reason}")
            if acc == "no":
                blockers.append("the selected track does not list this submission category")
            ctx.db.add(StudyTypeRecommendation(
                tenant_id=ctx.tenant_id, project_id=project_id, opportunity_id=o.id, study_type=d.study_type,
                venue_category=cat, fit_rationale=st.get("fit_rationale", ""), track_accepts=acc, track_rule_ref=ref,
                required_inputs=st.get("required_inputs") or [], reporting_standard=st.get("reporting_standard") or d.reporting_standard,
                blockers=blockers, method_enabled=d.enabled_for_submission_ready, method_availability=d.availability))
        f = feasibility_for(prop, dls, budget.as_dict())
        ctx.db.add(FeasibilityAssessment(tenant_id=ctx.tenant_id, project_id=project_id, opportunity_id=o.id, **f))
        stored += 1
    await ctx.db.commit()
    return {"stored": stored, "problems": problems, "at_least_two": stored >= 2}


def feasibility_for(prop: dict, deadlines: list[DeadlineObligation], budget: dict) -> dict:
    """Deterministic advisory feasibility from official deadlines and the proposal's (model) estimates."""
    now = utcnow()
    relevant = [d for d in deadlines if d.deadline_kind in ("abstract_registration", "full_paper") and d.applicability != "not_applicable"]
    dl_out = [{"kind": d.deadline_kind, "due_at": d.due_at.isoformat() if d.due_at else None,
               "stated_timezone": d.stated_timezone, "status": d.status} for d in relevant]
    lo, hi = int(prop.get("time_estimate_weeks_low") or 0), int(prop.get("time_estimate_weeks_high") or 0)
    writing, validation = 3, 1
    need_hi = (max(hi, lo) + writing + validation) * 7
    need_lo = (lo + writing + validation) * 7
    first_due = min((d.due_at for d in relevant if d.due_at), default=None)
    assumptions = [f"research {lo}-{hi} weeks (model estimate)", f"writing {writing} weeks and validation {validation} week (defaults)"]
    if first_due is None:
        status, slack, unc = "at_risk", None, "official deadline unknown or without timezone; feasibility cannot be computed"
    else:
        avail = (first_due - now).total_seconds() / 86400
        slack = round(avail - need_hi, 1)
        if avail < need_lo:
            status = "infeasible"
        elif avail < need_hi:
            status = "at_risk"
        else:
            status = "feasible"
        unc = f"{avail:.0f} days available vs {need_lo}-{need_hi} days estimated; estimates are uncertain"
    constraints = [c for c in (prop.get("data_availability"), prop.get("compute_estimate"), prop.get("ethics_constraints")) if c]
    return {"deadlines": dl_out, "estimates": {"research_weeks": [lo, hi], "writing_weeks": writing,
                                               "validation_weeks": validation, "source": "model estimate + defaults"},
            "cost_estimate": {"platform_budget_remaining_cents": budget["remaining_cents"], "currency": budget["currency"],
                              "note": "platform costs only; research costs are not estimated"},
            "constraints": constraints, "assumptions": assumptions, "status": status, "uncertainty": unc,
            "slack_days": slack}


_ = datetime
