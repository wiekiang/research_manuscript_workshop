"""M1 - CFP intelligence: official-source import, policy register, human resolution and the CFP gate."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.cfp import PRECEDENCE, SourceLevel, resolve_deadline
from rp_contracts.enums import Gate, ProjectState, RuleStatus
from rp_contracts.events import EventType
from rp_contracts.hashing import content_hash
from rp_contracts.netpolicy import FetchBlocked, validate_url
from rp_contracts.scanning import scan
from rp_contracts.textmatch import find_span

from ..db.base import utcnow
from ..db.models.cfp import (
    CfpRule,
    Conference,
    ConferenceEdition,
    DeadlineObligation,
    RuleResolution,
    SourceSnapshot,
    Track,
)
from ..db.models.core import Approval, Project
from ..deps import OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import approvals as approval_svc
from ..services import artifacts as art_svc
from ..services import invalidation
from ..services.approvals import DECLARATIONS
from ..services.common import audit, emit, notify
from ..services.gates import GateResult, gate
from ..services.tasks import create_task
from ..services.transitions import TransitionRequest, request_transition

router = APIRouter(tags=["cfp"])
SUPPLIED_TYPES = {"text/html", "application/pdf", "text/plain"}
MAX_SUPPLIED = 25 * 1024 * 1024


def series_key(name: str, acronym: str | None) -> str:
    base = acronym or name
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"\b(19|20)\d\d\b", "", base.lower())).strip("-")[:200] or "unknown"


def track_key(name: str | None) -> str:
    s = re.sub(r"\b(track|papers?|submissions?)\b", "", (name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip() or "main"


# --------------------------------------------------------------------------- researcher actions
class ImportIn(BaseModel):
    project_id: uuid.UUID
    url: str = Field(max_length=2048)
    source_level: SourceLevel = SourceLevel.TRACK_CFP
    note: str | None = Field(default=None, max_length=2000)


@router.post("/conferences/import", status_code=202)
async def import_cfp(body: ImportIn, ctx: Ctx = Depends(user_ctx),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """Queue a controlled fetch of an official CFP URL (nothing is fetched by the API itself)."""
    project, _ = await project_for(ctx, body.project_id, OWNER_ONLY)
    try:
        normalized, _, _ = validate_url(body.url)
    except FetchBlocked as exc:
        raise unprocessable("url_not_permitted", f"this URL cannot be fetched: {exc.reason}",
                            {"reason": exc.reason}) from exc
    task, created = await create_task(ctx.db, ctx.principal, project, "cfp_import",
                                      {"url": normalized, "source_level": body.source_level.value},
                                      idempotency_key=f"cfp_import:{project.id}:{idempotency_key}" if idempotency_key else None,
                                      input_manifest={"url": normalized, "requested_at": utcnow().isoformat()})
    await ctx.db.commit()
    return {"task": task_out(task), "created": created,
            "note": "The URL is fetched by the controlled fetch service; content becomes visible after scanning and commit."}


@router.post("/projects/{project_id}/cfp/documents", status_code=202)
async def supply_document(
    project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), file: UploadFile = File(...),
    declared_origin_url: str = Form(..., max_length=2048), origin_statement: str = Form(..., min_length=10, max_length=4000),
    source_level: SourceLevel = Form(SourceLevel.TRACK_CFP), attest_official: bool = Form(False),
):
    """Researcher-supplied official document with recorded provenance (used when fetching is not possible)."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    if not attest_official:
        raise unprocessable("attestation_required", "confirm that this document is the official CFP or policy text")
    data = await file.read(MAX_SUPPLIED + 1)
    if len(data) > MAX_SUPPLIED:
        raise unprocessable("file_too_large", "documents are limited to 25 MB")
    media = (file.content_type or "application/octet-stream").split(";")[0]
    report = scan(data, media)
    if report.sniffed_type not in SUPPLIED_TYPES or report.verdict == "rejected":
        raise unprocessable("file_rejected", "only HTML, PDF or plain-text documents that pass scanning are accepted",
                            report.to_dict())
    pub = await art_svc.publish_bytes(ctx.db, ctx.principal, ctx.tenant_id, project.id, "source_snapshot", data,
                                      report.sniffed_type, label=f"Supplied: {file.filename}"[:300],
                                      metadata={"declared_origin_url": declared_origin_url, "filename": file.filename,
                                                "scan": report.to_dict()},
                                      rights={"classification": "researcher_supplied", "model_use": "allowed_public_cfp"})
    snap = SourceSnapshot(tenant_id=ctx.tenant_id, project_id=project.id, origin="researcher_supplied",
                          source_level=source_level.value, url=declared_origin_url, final_url=None,
                          declared_origin=origin_statement, artifact_id=pub.artifact.id,
                          content_hash=pub.artifact.content_hash, media_type=report.sniffed_type,
                          retrieved_at=utcnow(), scan_report=report.to_dict(),
                          verification_status="researcher_declared_official", verified_by=ctx.principal.user_id,
                          verified_at=utcnow(), verification_note=origin_statement,
                          rights_classification="researcher_supplied")
    ctx.db.add(snap)
    await ctx.db.flush()
    task, _ = await create_task(ctx.db, ctx.principal, project, "cfp_extract_supplied",
                                {"snapshot_id": str(snap.id), "artifact_id": str(pub.artifact.id)},
                                input_manifest={"snapshot": pub.artifact.content_hash})
    await audit(ctx.db, ctx.principal, "cfp.document_supplied", project_id=project.id, resource_type="source_snapshot",
                resource_id=snap.id, details={"declared_origin_url": declared_origin_url, "hash": pub.artifact.content_hash})
    await ctx.db.commit()
    return {"snapshot_id": str(snap.id), "artifact_id": str(pub.artifact.id), "task": task_out(task)}


def rule_out(r: CfpRule, resolutions: list[RuleResolution] | None = None, track_name: str | None = None) -> dict:
    return {"id": str(r.id), "item_type": r.item_type, "rule_key": r.rule_key, "category": r.category,
            "track_id": str(r.track_id) if r.track_id else None, "track": track_name, "value_text": r.value_text,
            "value": r.value, "unit": r.unit, "blocking": r.blocking, "quote": r.quote, "locator": r.locator,
            "source_level": r.source_level, "snapshot_id": str(r.snapshot_id), "methods": r.methods,
            "verification_methods": [("model_assisted" if m == "model_assisted" else m) for m in r.methods],
            "agreement": r.agreement, "second_pass": r.second_pass, "problems": r.problems, "status": r.status,
            "is_current": r.is_current, "change_kind": r.change_kind, "conflict_group": r.conflict_group,
            "observations": r.observations,
            "resolutions": [{"id": str(x.id), "action": x.action, "resolved_value_text": x.resolved_value_text,
                             "resolved_value": x.resolved_value, "resolved_timezone": x.resolved_timezone,
                             "rationale": x.rationale, "at": x.created_at} for x in (resolutions or [])]}


async def _edition_view(db: AsyncSession, edition: ConferenceEdition, track_id: uuid.UUID | None) -> dict[str, Any]:
    conf = (await db.execute(select(Conference).where(Conference.id == edition.conference_id))).scalar_one()
    tracks = list((await db.execute(select(Track).where(Track.edition_id == edition.id))).scalars())
    names = {t.id: t.name for t in tracks}
    rules = list((await db.execute(select(CfpRule).where(CfpRule.edition_id == edition.id, CfpRule.is_current.is_(True))
                                   .order_by(CfpRule.item_type, CfpRule.rule_key))).scalars())
    res = list((await db.execute(select(RuleResolution).where(RuleResolution.rule_id.in_([r.id for r in rules])))).scalars()) if rules else []
    by_rule: dict[uuid.UUID, list[RuleResolution]] = {}
    for x in res:
        by_rule.setdefault(x.rule_id, []).append(x)
    applicable = [r for r in rules if track_id is None or r.track_id in (None, track_id)]
    deadlines = list((await db.execute(select(DeadlineObligation).where(
        DeadlineObligation.edition_id == edition.id, DeadlineObligation.is_current.is_(True)))).scalars())
    snaps = list((await db.execute(select(SourceSnapshot).where(SourceSnapshot.edition_id == edition.id)
                                   .order_by(SourceSnapshot.retrieved_at.desc()))).scalars())
    return {
        "conference": {"id": str(conf.id), "name": conf.name, "acronym": conf.acronym, "official_url": conf.official_url,
                       "questionable_flag": conf.questionable_flag, "questionable_evidence": conf.questionable_evidence},
        "edition": {"id": str(edition.id), "name": edition.name, "year": edition.year, "status": edition.status,
                    "location": edition.location, "official_cfp_url": edition.official_cfp_url,
                    "submission_url": edition.submission_url, "publication_outlet": edition.publication_outlet,
                    "venue_confidence": edition.venue_confidence},
        "tracks": [{"id": str(t.id), "name": t.name, "paper_types": t.paper_types, "description": t.description}
                   for t in tracks],
        "rules": [rule_out(r, by_rule.get(r.id), names.get(r.track_id)) for r in applicable],
        "deadlines": [{"id": str(d.id), "rule_id": str(d.rule_id), "deadline_kind": d.deadline_kind,
                       "track": names.get(d.track_id), "stated_date": d.stated_date, "stated_time": d.stated_time,
                       "stated_timezone": d.stated_timezone, "due_at": d.due_at, "mandatory": d.mandatory,
                       "governs_actions": d.governs_actions, "applicability": d.applicability, "status": d.status}
                      for d in deadlines if track_id is None or d.track_id in (None, track_id)],
        "snapshots": [snapshot_out(s) for s in snaps],
        "open_items": sum(1 for r in applicable if r.status == RuleStatus.NEEDS_HUMAN_RESOLUTION),
    }


def snapshot_out(s: SourceSnapshot) -> dict:
    return {"id": str(s.id), "origin": s.origin, "source_level": s.source_level, "url": s.url, "final_url": s.final_url,
            "artifact_id": str(s.artifact_id), "content_hash": s.content_hash, "media_type": s.media_type,
            "retrieved_at": s.retrieved_at, "verification_status": s.verification_status,
            "extraction_status": s.extraction_status, "scan_report": s.scan_report, "hops": s.hops,
            "declared_origin": s.declared_origin, "rights_classification": s.rights_classification}


@router.get("/projects/{project_id}/cfp")
async def project_cfp(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    snaps = list((await ctx.db.execute(select(SourceSnapshot).where(SourceSnapshot.project_id == project_id)
                                       .order_by(SourceSnapshot.retrieved_at.desc()))).scalars())
    edition_ids = list(dict.fromkeys([s.edition_id for s in snaps if s.edition_id] +
                                     ([project.target_edition_id] if project.target_edition_id else [])))
    editions = []
    for eid in edition_ids:
        ed = (await ctx.db.execute(select(ConferenceEdition).where(ConferenceEdition.id == eid))).scalar_one_or_none()
        if ed:
            view = await _edition_view(ctx.db, ed, project.target_track_id if eid == project.target_edition_id else None)
            view["is_target"] = eid == project.target_edition_id
            editions.append(view)
    gate_result = await cfp_confirmed(ctx.db, project)
    return {"target": {"mode": project.target_mode, "edition_id": str(project.target_edition_id) if project.target_edition_id else None,
                       "track_id": str(project.target_track_id) if project.target_track_id else None},
            "editions": editions, "pending_snapshots": [snapshot_out(s) for s in snaps if s.edition_id is None],
            "gate": gate_result.as_dict(), "declaration": {"version": DECLARATIONS[Gate.CFP].version,
                                                            "text": DECLARATIONS[Gate.CFP].text},
            "precedence": [p.value for p in PRECEDENCE]}


@router.get("/conferences")
async def list_conferences(ctx: Ctx = Depends(user_ctx)):
    rows = (await ctx.db.execute(select(ConferenceEdition, Conference).join(
        Conference, Conference.id == ConferenceEdition.conference_id).order_by(ConferenceEdition.created_at.desc()))).all()
    return {"items": [{"edition_id": str(e.id), "conference_id": str(c.id), "name": e.name, "acronym": c.acronym,
                       "year": e.year, "status": e.status, "official_cfp_url": e.official_cfp_url,
                       "venue_confidence": e.venue_confidence, "questionable_flag": c.questionable_flag}
                      for e, c in rows]}


class TargetIn(BaseModel):
    edition_id: uuid.UUID
    track_id: uuid.UUID | None = None
    mode: str = Field(pattern="^(official|exploratory)$")
    official_source_confirmed: bool = False
    expected_version: int


@router.post("/projects/{project_id}/target")
async def select_target(project_id: uuid.UUID, body: TargetIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    if project.version != body.expected_version:
        raise conflict("stale_version", "project changed; reload and retry")
    ed = (await ctx.db.execute(select(ConferenceEdition).where(ConferenceEdition.id == body.edition_id))).scalar_one_or_none()
    if ed is None:
        raise not_found("edition")
    if body.track_id:
        tr = (await ctx.db.execute(select(Track).where(Track.id == body.track_id, Track.edition_id == ed.id))).scalar_one_or_none()
        if tr is None:
            raise not_found("track")
    if body.mode == "official":
        if not body.official_source_confirmed:
            raise unprocessable("official_source_unconfirmed",
                                "confirm that the snapshot comes from the organizer's official CFP page")
        if not body.track_id:
            raise unprocessable("track_required", "select the track you will submit to")
        snap = (await ctx.db.execute(select(SourceSnapshot).where(SourceSnapshot.edition_id == ed.id)
                                     .order_by(SourceSnapshot.retrieved_at.desc()))).scalars().first()
        if snap is None:
            raise unprocessable("no_source", "import the official CFP before selecting an official target")
        if snap.verification_status in ("unverified", "researcher_declared_official"):
            snap.verification_status = "official_confirmed_by_researcher"
            snap.verified_by = ctx.principal.user_id
            snap.verified_at = utcnow()
        ed.status = "official"
        ed.verified_by = ctx.principal.user_id
        ed.verified_at = utcnow()
    changed = (project.target_edition_id, project.target_track_id) != (ed.id, body.track_id)
    project.target_edition_id = ed.id
    project.target_track_id = body.track_id
    project.target_mode = body.mode
    project.version += 1
    await audit(ctx.db, ctx.principal, "project.target_selected", project_id=project.id,
                details={"edition_id": str(ed.id), "track_id": str(body.track_id) if body.track_id else None,
                         "mode": body.mode})
    if changed:
        # A different track/edition invalidates any CFP confirmation bound to the previous ruleset.
        prior = list((await ctx.db.execute(select(Approval).where(Approval.project_id == project.id,
                                                                  Approval.gate == Gate.CFP.value,
                                                                  Approval.status == "valid"))).scalars())
        for a in prior:
            await approval_svc.invalidate_approval(ctx.db, ctx.principal, a, "target edition/track changed")
    result = None
    if project.state == ProjectState.CREATED:
        result = (await request_transition(ctx.db, ctx.principal, project.id, TransitionRequest(
            requested_state=ProjectState.TARGET_REVIEW, expected_project_version=project.version,
            idempotency_key=f"target:{project.id}:{project.version}"))).as_dict()
    elif changed and project.state != ProjectState.TARGET_REVIEW:
        from ..services.transitions import reopen_to

        tr = await reopen_to(ctx.db, ctx.principal, project, ProjectState.TARGET_REVIEW, "target changed",
                             f"target-reopen:{project.id}:{project.version}")
        result = tr.as_dict() if tr else None
    await ctx.db.commit()
    return {"target_mode": project.target_mode, "edition_id": str(ed.id),
            "track_id": str(body.track_id) if body.track_id else None, "state": project.state,
            "version": project.version, "transition": result}


class ResolveIn(BaseModel):
    rule_id: uuid.UUID
    action: str = Field(pattern="^(confirm|reject|edit|not_applicable)$")
    value_text: str | None = Field(default=None, max_length=4000)
    value: str | None = Field(default=None, max_length=400)
    timezone: str | None = Field(default=None, max_length=80)
    time: str | None = Field(default=None, max_length=10)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    rationale: str = Field(min_length=5, max_length=4000)


def _rule_hash(r: CfpRule) -> str:
    return content_hash({"id": str(r.id), "value_text": r.value_text, "value": r.value, "quote": r.quote,
                         "snapshot": str(r.snapshot_id)})


@router.post("/projects/{project_id}/cfp/resolve")
async def resolve_rule(project_id: uuid.UUID, body: ResolveIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    r = (await ctx.db.execute(select(CfpRule).where(CfpRule.id == body.rule_id, CfpRule.is_current.is_(True)))).scalar_one_or_none()
    if r is None:
        raise not_found("rule")
    if body.action == "edit" and not (body.value_text or body.value or body.timezone or body.time or body.date):
        raise unprocessable("edit_requires_value", "an edit must state the interpreted value")
    res = RuleResolution(tenant_id=ctx.tenant_id, rule_id=r.id, project_id=project.id, action=body.action,
                         resolved_value_text=body.value_text, resolved_value=body.value,
                         resolved_timezone=body.timezone, resolved_time=body.time, rationale=body.rationale,
                         actor_id=ctx.principal.user_id, rule_hash=_rule_hash(r))
    ctx.db.add(res)
    await ctx.db.flush()
    if body.action == "reject":
        r.status = RuleStatus.REJECTED
    else:
        r.status = RuleStatus.CONFIRMED
        r.verified_at = utcnow()
    if r.item_type == "deadline":
        dl = (await ctx.db.execute(select(DeadlineObligation).where(DeadlineObligation.rule_id == r.id,
                                                                    DeadlineObligation.is_current.is_(True)))).scalar_one_or_none()
        if dl is not None:
            if body.action == "not_applicable":
                dl.applicability = "not_applicable"
            if body.timezone or body.time or body.date:
                tz = body.timezone or dl.stated_timezone
                tm = body.time or dl.stated_time
                rd = resolve_deadline(body.date or dl.stated_date or "", tm, tz)
                if rd.due_at is None:
                    raise unprocessable("unresolvable_deadline", "; ".join(rd.problems))
                dl.due_at = rd.due_at
                if body.date:
                    dl.stated_date = body.date
            elif dl.due_at is None and body.action != "not_applicable" and body.action != "reject":
                raise unprocessable("timezone_required", "state the timezone (and time) that the official source uses")
            dl.status = r.status
            dl.human_resolution_id = res.id
    await audit(ctx.db, ctx.principal, "cfp.rule_resolved", project_id=project.id, resource_type="cfp_rule",
                resource_id=r.id, details={"action": body.action, "rule_key": r.rule_key})
    await ctx.db.commit()
    return rule_out(r, [res])


class ConfirmIn(BaseModel):
    declaration_accepted: bool
    declaration_text: str
    rationale: str | None = Field(default=None, max_length=4000)


async def current_ruleset(db: AsyncSession, project: Project) -> dict[str, Any]:
    rules = list((await db.execute(select(CfpRule).where(
        CfpRule.edition_id == project.target_edition_id, CfpRule.is_current.is_(True), CfpRule.item_type == "rule",
        (CfpRule.track_id.is_(None)) | (CfpRule.track_id == project.target_track_id)).order_by(CfpRule.rule_key))).scalars())
    res = {x.rule_id: x for x in (await db.execute(select(RuleResolution).where(
        RuleResolution.rule_id.in_([r.id for r in rules])).order_by(RuleResolution.created_at))).scalars()} if rules else {}
    snaps = {s.id: s.content_hash for s in (await db.execute(select(SourceSnapshot).where(
        SourceSnapshot.id.in_({r.snapshot_id for r in rules})))).scalars()} if rules else {}
    return {"edition_id": str(project.target_edition_id), "track_id": str(project.target_track_id),
            "rules": [{"id": str(r.id), "rule_key": r.rule_key, "value_text": r.value_text, "value": r.value,
                       "status": r.status, "blocking": r.blocking, "source_snapshot_hash": snaps.get(r.snapshot_id),
                       "resolution": ({"action": res[r.id].action, "value": res[r.id].resolved_value,
                                       "value_text": res[r.id].resolved_value_text} if r.id in res else None)}
                      for r in rules]}


async def current_schedule(db: AsyncSession, project: Project) -> dict[str, Any]:
    dls = list((await db.execute(select(DeadlineObligation).where(
        DeadlineObligation.edition_id == project.target_edition_id, DeadlineObligation.is_current.is_(True),
        (DeadlineObligation.track_id.is_(None)) | (DeadlineObligation.track_id == project.target_track_id))
        .order_by(DeadlineObligation.deadline_kind))).scalars())
    return {"edition_id": str(project.target_edition_id), "track_id": str(project.target_track_id),
            "deadlines": [{"id": str(d.id), "kind": d.deadline_kind, "due_at": d.due_at.isoformat() if d.due_at else None,
                           "timezone": d.stated_timezone, "governs": d.governs_actions, "mandatory": d.mandatory,
                           "applicability": d.applicability, "status": d.status} for d in dls]}


@router.post("/projects/{project_id}/cfp/confirm")
async def confirm_cfp(project_id: uuid.UUID, body: ConfirmIn, ctx: Ctx = Depends(user_ctx)):
    """CFP gate: the researcher confirms the track and every blocking rule against the official snapshot."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY, lock=True)
    pre = await _cfp_preconditions(ctx.db, project)
    if pre:
        raise ApiError(422, "gate_unsatisfied", "resolve these items before confirming", {"reasons": pre})
    ruleset = await current_ruleset(ctx.db, project)
    schedule = await current_schedule(ctx.db, project)
    rs = await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project.id, "cfp_ruleset", ruleset,
                                    label="Confirmed CFP ruleset")
    sc = await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project.id, "deadline_schedule", schedule,
                                    label="Deadline schedule")
    appr = await approval_svc.record_approval(ctx.db, ctx.principal, project, Gate.CFP, [rs.artifact],
                                              declaration_accepted=body.declaration_accepted,
                                              declaration_text=body.declaration_text, rationale=body.rationale)
    result = None
    if project.state == ProjectState.TARGET_REVIEW:
        result = (await request_transition(ctx.db, ctx.principal, project.id, TransitionRequest(
            requested_state=ProjectState.DIRECTION_REVIEW, expected_project_version=project.version,
            idempotency_key=f"cfp-confirm:{appr.id}", human_approval_id=appr.id, cause="approval"))).as_dict()
    else:
        from ..services.progress import fast_forward

        result = await fast_forward(ctx.db, ctx.principal, project)
    await ctx.db.commit()
    return {"approval_id": str(appr.id), "ruleset_artifact_id": str(rs.artifact.id),
            "schedule_artifact_id": str(sc.artifact.id), "transition": result, "state": project.state}


# --------------------------------------------------------------------------- gate evaluators
async def _cfp_preconditions(db: AsyncSession, project: Project) -> list[str]:
    reasons = []
    if project.target_edition_id is None or project.target_track_id is None:
        reasons.append("select the official conference edition and track")
        return reasons
    if project.target_mode != "official":
        reasons.append("the target is exploratory; compliance and template stages need an official CFP source")
    open_rules = list((await db.execute(select(CfpRule).where(
        CfpRule.edition_id == project.target_edition_id, CfpRule.is_current.is_(True),
        CfpRule.status == RuleStatus.NEEDS_HUMAN_RESOLUTION,
        (CfpRule.track_id.is_(None)) | (CfpRule.track_id == project.target_track_id)))).scalars())
    for r in open_rules:
        reasons.append(f"resolve {r.rule_key}: {'; '.join(r.problems) or 'needs confirmation'}")
    snap = (await db.execute(select(SourceSnapshot).where(SourceSnapshot.edition_id == project.target_edition_id)
                             .order_by(SourceSnapshot.retrieved_at.desc()))).scalars().first()
    if snap is None:
        reasons.append("no official source snapshot")
    elif snap.verification_status not in ("official_confirmed_by_researcher", "researcher_declared_official"):
        reasons.append("the official status of the source has not been confirmed")
    return reasons


@gate("target.selected")
async def target_selected(db: AsyncSession, project: Project) -> GateResult:
    if project.target_edition_id is None:
        return GateResult("target.selected", False, ["no conference edition selected"],
                          next_action="Import an official CFP URL and select the edition and track")
    return GateResult("target.selected", True, evidence={"mode": project.target_mode})


@gate("cfp.confirmed")
async def cfp_confirmed(db: AsyncSession, project: Project) -> GateResult:
    reasons = await _cfp_preconditions(db, project)
    appr, problems = await approval_svc.current_approval(db, project.id, Gate.CFP)
    if appr is None:
        reasons.append("confirm the selected track and its blocking rules (CFP gate)")
    else:
        reasons += problems
        ruleset = await current_ruleset(db, project)
        bound = next((b for b in appr.bound_artifacts if b.get("kind") == "cfp_ruleset"), None)
        from rp_contracts.hashing import canonical_json, sha256_hex

        if bound and bound["hash"] != sha256_hex(canonical_json(ruleset)):
            reasons.append("CFP rules changed since they were confirmed; review and confirm again")
    return GateResult("cfp.confirmed", not reasons, reasons,
                      evidence={"approval_id": str(appr.id)} if appr else {},
                      next_action="Resolve open CFP items and confirm the track rules" if reasons else None)


# --------------------------------------------------------------------------- worker ingestion
class SnapshotIn(BaseModel):
    project_id: uuid.UUID
    url: str
    final_url: str
    artifact_id: uuid.UUID
    text_artifact_id: uuid.UUID | None = None
    retrieved_at: datetime
    http_status: int
    etag: str | None = None
    last_modified: str | None = None
    media_type: str
    scan_report: dict[str, Any]
    hops: list[dict[str, Any]]
    source_level: SourceLevel = SourceLevel.TRACK_CFP
    robots: str = "not_checked"


@router.post("/internal/cfp/snapshots", status_code=201)
async def register_snapshot(body: SnapshotIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, body.project_id, "domain.write")
    require_task_kind(ctx, "cfp_import", "cfp_monitor")
    art = await art_svc.get_artifact(ctx.db, body.artifact_id, body.project_id)
    if art.kind != "source_snapshot":
        raise unprocessable("wrong_kind", "artifact must be a committed source_snapshot")
    existing = (await ctx.db.execute(select(SourceSnapshot).where(SourceSnapshot.artifact_id == art.id,
                                                                  SourceSnapshot.project_id == body.project_id))).scalars().first()
    if existing:
        return snapshot_out(existing)
    snap = SourceSnapshot(tenant_id=ctx.tenant_id, project_id=body.project_id, origin="fetched",
                          source_level=body.source_level.value, url=body.url, final_url=body.final_url,
                          artifact_id=art.id, text_artifact_id=body.text_artifact_id, content_hash=art.content_hash,
                          media_type=body.media_type, http_status=body.http_status, etag=body.etag,
                          last_modified=body.last_modified, retrieved_at=body.retrieved_at, hops=body.hops,
                          scan_report={**body.scan_report, "robots": body.robots})
    ctx.db.add(snap)
    await ctx.db.commit()
    return snapshot_out(snap)


class TextIn(BaseModel):
    text_artifact_id: uuid.UUID


@router.post("/internal/cfp/snapshots/{snapshot_id}/text")
async def register_text(snapshot_id: uuid.UUID, body: TextIn, ctx: Ctx = Depends(service_ctx)):
    snap = (await ctx.db.execute(select(SourceSnapshot).where(SourceSnapshot.id == snapshot_id))).scalar_one_or_none()
    if snap is None:
        raise not_found("snapshot")
    require_service_scope(ctx, snap.project_id, "domain.write")
    await art_svc.require_committed(ctx.db, [body.text_artifact_id], snap.project_id)
    snap.text_artifact_id = body.text_artifact_id
    await ctx.db.commit()
    return snapshot_out(snap)


@router.get("/internal/cfp/snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    snap = (await ctx.db.execute(select(SourceSnapshot).where(SourceSnapshot.id == snapshot_id))).scalar_one_or_none()
    if snap is None:
        raise not_found("snapshot")
    require_service_scope(ctx, snap.project_id, "domain.read")
    return snapshot_out(snap)


class ExtractionIn(BaseModel):
    snapshot_id: uuid.UUID
    extraction_artifact_id: uuid.UUID
    validation_artifact_id: uuid.UUID
    merged: dict[str, Any]


@router.post("/internal/projects/{project_id}/cfp/extraction")
async def ingest_extraction(project_id: uuid.UUID, body: ExtractionIn, ctx: Ctx = Depends(service_ctx)):
    """Persist source-linked rules. Contradictions, missing timezones and unverified quotes stay
    needs_human_resolution; a changed rule supersedes its predecessor and invalidates dependent confirmations."""
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "cfp_import", "cfp_extract_supplied", "cfp_monitor")
    project, _ = await project_for(ctx, project_id)
    await art_svc.require_committed(ctx.db, [body.extraction_artifact_id, body.validation_artifact_id], project_id)
    snap = (await ctx.db.execute(select(SourceSnapshot).where(SourceSnapshot.id == body.snapshot_id,
                                                              SourceSnapshot.project_id == project_id))).scalar_one_or_none()
    if snap is None:
        raise not_found("snapshot")
    if snap.extraction_status == "ingested":
        return {"snapshot_id": str(snap.id), "edition_id": str(snap.edition_id), "replayed": True}
    m = body.merged
    new_text = ""
    if snap.text_artifact_id:
        new_text = (await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, snap.text_artifact_id)))["text"]
    ed_info = m["edition"]
    skey = series_key(ed_info.get("conference_name") or "conference", ed_info.get("acronym"))
    conf = (await ctx.db.execute(select(Conference).where(Conference.series_key == skey))).scalar_one_or_none()
    if conf is None:
        conf = Conference(tenant_id=ctx.tenant_id, name=ed_info.get("conference_name") or skey,
                          acronym=ed_info.get("acronym"), series_key=skey, official_url=ed_info.get("official_site_url"))
        ctx.db.add(conf)
        await ctx.db.flush()
    year = ed_info.get("year")
    ed = (await ctx.db.execute(select(ConferenceEdition).where(ConferenceEdition.conference_id == conf.id,
                                                               ConferenceEdition.year == year)
                               .with_for_update())).scalar_one_or_none()  # serialise ingestion per edition
    if ed is None:
        ed = ConferenceEdition(tenant_id=ctx.tenant_id, conference_id=conf.id, year=year,
                               name=ed_info.get("conference_name") or conf.name,
                               official_cfp_url=snap.final_url or snap.url, location=ed_info.get("location"),
                               submission_url=ed_info.get("submission_url"),
                               publication_outlet=ed_info.get("publication_outlet"), publisher=ed_info.get("publisher"),
                               venue_confidence="source_recorded",
                               venue_confidence_rationale="Edition derived from a recorded snapshot; official status is "
                                                          "confirmed by the researcher, not inferred.")
        ctx.db.add(ed)
        await ctx.db.flush()
    snap.edition_id = ed.id
    ed.latest_snapshot_id = snap.id
    track_ids: dict[str, uuid.UUID] = {}
    for t in m.get("tracks", []):
        k = track_key(t["name"])
        tr = (await ctx.db.execute(select(Track).where(Track.edition_id == ed.id, Track.normalized_key == k))).scalar_one_or_none()
        if tr is None:
            tr = Track(tenant_id=ctx.tenant_id, edition_id=ed.id, name=t["name"], normalized_key=k,
                       description=t.get("description"), paper_types=t.get("paper_types") or [],
                       submission_categories=t.get("submission_categories") or [], source_quote=t.get("quote"))
            ctx.db.add(tr)
            await ctx.db.flush()
        track_ids[k] = tr.id

    changed_rules: list[str] = []
    changed_deadlines: list[str] = []
    for item in m["items"]:
        tid = track_ids.get(track_key(item.get("track"))) if item.get("track") else None
        if item.get("track") and tid is None:
            tr = Track(tenant_id=ctx.tenant_id, edition_id=ed.id, name=item["track"], normalized_key=track_key(item["track"]))
            ctx.db.add(tr)
            await ctx.db.flush()
            tid = track_ids[track_key(item["track"])] = tr.id
        prev = (await ctx.db.execute(select(CfpRule).where(
            CfpRule.edition_id == ed.id, CfpRule.rule_key == item["rule_key"], CfpRule.is_current.is_(True),
            CfpRule.track_id.is_(None) if tid is None else CfpRule.track_id == tid,
            CfpRule.source_level == snap.source_level))).scalars().first()
        status = item["status"]
        problems = list(item["problems"])
        change_kind = "new"
        if prev is not None:
            # Change detection compares the official source, not extractor output: the rule is unchanged when the
            # sentence it was confirmed against still appears verbatim in the new snapshot.
            source_unchanged = bool(prev.quote) and find_span(new_text, prev.quote) is not None
            if source_unchanged:
                change_kind = "unchanged"
                if prev.status == RuleStatus.CONFIRMED:
                    status = RuleStatus.CONFIRMED.value
                    problems = []
                    item = {**item, "value": prev.value, "value_text": prev.value_text, "quote": prev.quote,
                            "locator": item.get("locator") or prev.locator}
            else:
                change_kind = "changed"
                status = RuleStatus.NEEDS_HUMAN_RESOLUTION.value
                problems.append(f"changed since the previous snapshot (was: {prev.value or prev.value_text[:120]})")
                (changed_deadlines if item["item_type"] == "deadline" else changed_rules).append(item["rule_key"])
            prev.is_current = False
        # Conflicts with a different precedence level for the same key are never auto-resolved.
        other_levels = list((await ctx.db.execute(select(CfpRule).where(
            CfpRule.edition_id == ed.id, CfpRule.rule_key == item["rule_key"], CfpRule.is_current.is_(True),
            CfpRule.source_level != snap.source_level))).scalars())
        conflict_group = None
        for o in other_levels:
            if (o.value or o.value_text) != (item.get("value") or item.get("value_text")):
                conflict_group = f"{ed.id}:{item['rule_key']}"
                o.conflict_group = conflict_group
                o.status = RuleStatus.NEEDS_HUMAN_RESOLUTION
                status = RuleStatus.NEEDS_HUMAN_RESOLUTION.value
                problems.append(f"conflicts with {o.source_level} source; precedence does not silently pick a winner")
        rule = CfpRule(tenant_id=ctx.tenant_id, edition_id=ed.id, track_id=tid, snapshot_id=snap.id,
                       item_type=item["item_type"], rule_key=item["rule_key"], category=item["category"],
                       value_text=item.get("value_text") or "", value=item.get("value"), unit=item.get("unit"),
                       blocking=bool(item.get("blocking")), quote=item.get("quote"), locator=item.get("locator"),
                       source_level=snap.source_level, methods=item["methods"], agreement=item["agreement"],
                       second_pass=item.get("second_pass") or {}, observations=item.get("observations") or [],
                       problems=problems, status=status, change_kind=change_kind,
                       previous_rule_id=prev.id if prev else None, conflict_group=conflict_group,
                       extractor_versions={"merge": m.get("merge_version"), "passes": m.get("passes")})
        ctx.db.add(rule)
        await ctx.db.flush()
        if prev is not None:
            prev.superseded_by = rule.id
        if item["item_type"] == "deadline":
            carried = None
            if prev is not None:
                for old in (await ctx.db.execute(select(DeadlineObligation).where(DeadlineObligation.rule_id == prev.id))).scalars():
                    old.is_current = False
                    carried = old if change_kind == "unchanged" else None
            if carried is not None and carried.status == RuleStatus.CONFIRMED:
                item = {**item, "date": carried.stated_date, "time": carried.stated_time,
                        "timezone": carried.stated_timezone,
                        "due_at": carried.due_at.isoformat() if carried.due_at else None}
            ctx.db.add(DeadlineObligation(
                tenant_id=ctx.tenant_id, edition_id=ed.id, track_id=tid, rule_id=rule.id,
                deadline_kind=item["deadline_kind"], governs_actions=item.get("governs_actions") or [],
                mandatory=item.get("mandatory"), stated_date=item.get("date"), stated_time=item.get("time"),
                stated_timezone=item.get("timezone"),
                due_at=datetime.fromisoformat(item["due_at"]) if item.get("due_at") else None,
                applicability="applies" if item.get("track") is None or tid is not None else "unknown",
                status=status))
    # Earlier rules that this extraction did not re-find: still current only if their source sentence survives.
    seen_ids = {r for r in (await ctx.db.execute(select(CfpRule.id).where(CfpRule.snapshot_id == snap.id))).scalars()}
    leftovers = list((await ctx.db.execute(select(CfpRule).where(
        CfpRule.edition_id == ed.id, CfpRule.is_current.is_(True), CfpRule.snapshot_id != snap.id,
        CfpRule.source_level == snap.source_level))).scalars())
    for old in leftovers:
        if old.id in seen_ids or old.status == RuleStatus.REJECTED:
            continue
        if new_text and old.quote and find_span(new_text, old.quote) is None:
            old.status = RuleStatus.NEEDS_HUMAN_RESOLUTION
            old.change_kind = "removed"
            old.problems = [*old.problems, "its source sentence no longer appears in the latest official snapshot"]
            (changed_deadlines if old.item_type == "deadline" else changed_rules).append(old.rule_key)
    snap.extraction_status = "ingested"
    effects = []
    if changed_rules or changed_deadlines:
        emit(ctx.db, tenant_id=ctx.tenant_id, type=EventType.RULE_CHANGED, actor_type="service",
             actor_id=ctx.principal.actor_id, project_id=project_id,
             payload={"edition_id": str(ed.id), "rules": changed_rules, "deadlines": changed_deadlines})
        effects = await _apply_rule_changes(ctx, ed.id, changed_rules, changed_deadlines)
    await audit(ctx.db, ctx.principal, "cfp.extraction_ingested", project_id=project_id, resource_type="source_snapshot",
                resource_id=snap.id, details={"items": len(m["items"]), "changed_rules": changed_rules,
                                              "changed_deadlines": changed_deadlines, "passes": m.get("passes")})
    await ctx.db.commit()
    open_items = sum(1 for i in m["items"] if i["status"] == "needs_human_resolution")
    return {"snapshot_id": str(snap.id), "edition_id": str(ed.id), "items": len(m["items"]), "open_items": open_items,
            "changed_rules": changed_rules, "changed_deadlines": changed_deadlines, "effects": effects}


async def _apply_rule_changes(ctx: Ctx, edition_id: uuid.UUID, rules: list[str], deadlines: list[str]) -> list[str]:
    """Invalidate only what consumed the changed rules. Deadline-only changes refresh the schedule/eligibility
    (M8) but never invalidate the CFP confirmation, H4 or scientific findings."""
    from ..db.models.core import Artifact

    effects: list[str] = []
    projects = list((await ctx.db.execute(select(Project).where(Project.target_edition_id == edition_id))).scalars())
    for p in projects:
        if rules:
            arts = list((await ctx.db.execute(select(Artifact).where(
                Artifact.project_id == p.id, Artifact.kind == "cfp_ruleset", Artifact.freshness == "current"))).scalars())
            if arts:
                res = await invalidation.invalidate(ctx.db, ctx.principal, p, [a.id for a in arts],
                                                    f"official CFP rules changed: {', '.join(rules)}",
                                                    f"rule-change:{p.id}:{uuid.uuid4()}")
                effects.append(f"{p.id}: CFP confirmation reopened ({res.reopened_to or p.state})")
        if deadlines:
            arts = list((await ctx.db.execute(select(Artifact).where(
                Artifact.project_id == p.id, Artifact.kind.in_(["deadline_schedule", "eligibility_assessment"]),
                Artifact.freshness == "current"))).scalars())
            if arts:
                await invalidation.invalidate(ctx.db, ctx.principal, p, [a.id for a in arts],
                                              f"official deadlines changed: {', '.join(deadlines)}",
                                              f"deadline-change:{p.id}:{uuid.uuid4()}")
                effects.append(f"{p.id}: deadline schedule and eligibility marked stale")
        owner = p.owner_id
        notify(ctx.db, tenant_id=p.tenant_id, user_id=owner, project_id=p.id, type="rule.changed",
               title=f"{p.title}: the official CFP changed",
               body=f"Changed rules: {', '.join(rules) or 'none'}; deadlines: {', '.join(deadlines) or 'none'}.",
               link=f"/projects/{p.id}/cfp", dedupe_key=f"{p.tenant_id}:rulechange:{p.id}:{content_hash([rules, deadlines])[:16]}:{utcnow().date()}")
    return effects
