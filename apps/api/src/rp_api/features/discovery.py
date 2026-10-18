"""M2 - automatic official-source discovery, relevance ranking, deadline and CFP-change monitoring."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from rp_contracts.netpolicy import FetchBlocked, validate_url
from rp_contracts.ranking import ResearchProfile as ProfileModel

from ..config import get_settings
from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.cfp import (
    CfpMonitorCheck,
    ConferenceCandidate,
    ConferenceEdition,
    DeadlineObligation,
    ResearchProfile,
    SourceSnapshot,
    VenueRegistryEntry,
)
from ..db.models.core import Project, ProjectMember, User
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, forbidden, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services.common import audit, notify
from ..services.tasks import create_task

router = APIRouter(tags=["discovery"])


# --------------------------------------------------------------------------- research profile
class ProfileIn(ProfileModel):
    project_id: uuid.UUID | None = None


async def effective_profile(db, user_id: uuid.UUID, project_id: uuid.UUID | None) -> dict[str, Any]:
    rows = list((await db.execute(select(ResearchProfile).where(ResearchProfile.user_id == user_id))).scalars())
    base = next((r.profile for r in rows if r.project_id is None), {})
    proj = next((r.profile for r in rows if r.project_id == project_id), None) if project_id else None
    return {**base, **(proj or {})}


@router.get("/research-profile")
async def get_profile(project_id: uuid.UUID | None = None, ctx: Ctx = Depends(user_ctx)):
    prof = await effective_profile(ctx.db, ctx.principal.user_id, project_id)
    return {"profile": ProfileModel(**prof).model_dump(), "project_id": str(project_id) if project_id else None}


@router.put("/research-profile")
async def put_profile(body: ProfileIn, ctx: Ctx = Depends(user_ctx)):
    if body.project_id:
        await project_for(ctx, body.project_id, EDIT_ROLES)
    row = (await ctx.db.execute(select(ResearchProfile).where(
        ResearchProfile.user_id == ctx.principal.user_id,
        ResearchProfile.project_id.is_(None) if body.project_id is None else ResearchProfile.project_id == body.project_id
    ))).scalar_one_or_none()
    data = body.model_dump(exclude={"project_id"})
    if row is None:
        row = ResearchProfile(tenant_id=ctx.tenant_id, user_id=ctx.principal.user_id, project_id=body.project_id, profile=data)
        ctx.db.add(row)
    else:
        row.profile = data
        row.version += 1
    await ctx.db.commit()
    return {"profile": data}


# --------------------------------------------------------------------------- discovery
@router.post("/projects/{project_id}/discovery", status_code=202)
async def run_discovery(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    profile = await effective_profile(ctx.db, ctx.principal.user_id, project_id)
    if not profile.get("topics"):
        raise unprocessable("profile_incomplete", "add research topics to your profile before discovery")
    async with session_scope("app") as gdb:
        verified = (await gdb.execute(select(VenueRegistryEntry.id).where(
            VenueRegistryEntry.verification_status == "verified"))).scalars().all()
    if not verified:
        raise unprocessable("registry_empty", "the curated official-source registry has no verified entries yet; "
                                              "use manual CFP import or ask a platform operator to verify sources")
    task, created = await create_task(ctx.db, ctx.principal, project, "conference_discovery",
                                      {"profile": profile, "registry_entry_ids": [str(i) for i in verified]},
                                      input_manifest={"profile": profile, "registry": sorted(str(i) for i in verified),
                                                      "day": utcnow().date().isoformat()})
    await ctx.db.commit()
    return {"task": task_out(task), "created": created}


def candidate_out(c: ConferenceCandidate) -> dict:
    return {"id": str(c.id), "rank": c.rank, "name": c.name, "acronym": c.acronym, "year": c.year,
            "official_url": c.official_url, "tracks": c.tracks, "deadlines": c.deadlines, "location": c.location,
            "publisher": c.publisher, "total_score": c.total_score, "components": c.components,
            "excluded": c.excluded, "exclusion_reason": c.exclusion_reason,
            "questionable_evidence": c.questionable_evidence, "status": c.status, "snapshot_hash": c.snapshot_hash,
            "note": "Scores are component estimates from the official CFP text and your profile, not a venue "
                    "reputation judgement. Import the CFP to obtain verified rules."}


@router.get("/projects/{project_id}/candidates")
async def candidates(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), include_excluded: bool = False):
    await project_for(ctx, project_id)
    q = select(ConferenceCandidate).where(ConferenceCandidate.project_id == project_id,
                                          ConferenceCandidate.is_current.is_(True))
    if not include_excluded:
        q = q.where(ConferenceCandidate.excluded.is_(False))
    rows = (await ctx.db.execute(q.order_by(ConferenceCandidate.rank))).scalars()
    return {"items": [candidate_out(c) for c in rows]}


@router.post("/projects/{project_id}/candidates/{candidate_id}/import", status_code=202)
async def import_candidate(project_id: uuid.UUID, candidate_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    c = (await ctx.db.execute(select(ConferenceCandidate).where(ConferenceCandidate.id == candidate_id,
                                                                ConferenceCandidate.project_id == project_id))).scalar_one_or_none()
    if c is None:
        raise not_found("candidate")
    task, created = await create_task(ctx.db, ctx.principal, project, "cfp_import",
                                      {"url": c.official_url, "source_level": "track_cfp", "candidate_id": str(c.id)},
                                      input_manifest={"url": c.official_url, "candidate": str(c.id)})
    c.status = "imported"
    await ctx.db.commit()
    return {"task": task_out(task), "created": created}


@router.post("/projects/{project_id}/candidates/{candidate_id}/dismiss")
async def dismiss_candidate(project_id: uuid.UUID, candidate_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, OWNER_ONLY)
    c = (await ctx.db.execute(select(ConferenceCandidate).where(ConferenceCandidate.id == candidate_id,
                                                                ConferenceCandidate.project_id == project_id))).scalar_one_or_none()
    if c is None:
        raise not_found("candidate")
    c.status = "dismissed"
    await ctx.db.commit()
    return candidate_out(c)


# --------------------------------------------------------------------------- monitoring (researcher-triggered)
@router.post("/projects/{project_id}/cfp/check-now", status_code=202)
async def check_now(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    task = await _create_monitor_task(ctx, project)
    await ctx.db.commit()
    return {"task": task_out(task) if task else None}


@router.get("/projects/{project_id}/cfp/monitor")
async def monitor_history(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(CfpMonitorCheck).where(CfpMonitorCheck.project_id == project_id)
                                 .order_by(CfpMonitorCheck.created_at.desc()).limit(100))).scalars()
    return {"items": [{"id": str(r.id), "url": r.url, "outcome": r.outcome, "detail": r.detail,
                       "snapshot_id": str(r.snapshot_id) if r.snapshot_id else None, "at": r.created_at} for r in rows]}


async def _create_monitor_task(ctx: Ctx, project: Project):
    from ..db.models.core import WorkflowTask

    pending = (await ctx.db.execute(select(WorkflowTask).where(
        WorkflowTask.project_id == project.id, WorkflowTask.kind == "cfp_monitor",
        WorkflowTask.state.in_(["queued", "running", "failed_retryable"])))).scalars().first()
    if pending is not None:
        return pending
    if project.target_edition_id is None:
        raise unprocessable("no_target", "select an official target before monitoring its CFP")
    snap = (await ctx.db.execute(select(SourceSnapshot).where(
        SourceSnapshot.edition_id == project.target_edition_id, SourceSnapshot.origin == "fetched")
        .order_by(SourceSnapshot.retrieved_at.desc()))).scalars().first()
    if snap is None or not snap.url:
        raise unprocessable("no_fetched_source", "the target CFP was supplied as a document; re-import it from its "
                                                 "official URL to enable monitoring")
    task, _ = await create_task(ctx.db, ctx.principal, project, "cfp_monitor",
                                {"url": snap.final_url or snap.url, "etag": snap.etag, "last_modified": snap.last_modified,
                                 "previous_hash": snap.content_hash, "edition_id": str(project.target_edition_id),
                                 "source_level": snap.source_level},
                                input_manifest={"edition": str(project.target_edition_id), "at": utcnow().isoformat()})
    return task


# --------------------------------------------------------------------------- internal (workers)
@router.get("/internal/registry")
async def registry_for_task(ctx: Ctx = Depends(service_ctx)):
    require_task_kind(ctx, "conference_discovery")
    rows = (await ctx.db.execute(select(VenueRegistryEntry).where(VenueRegistryEntry.verification_status == "verified"))).scalars()
    return {"items": [{"id": str(r.id), "series_key": r.series_key, "name": r.name, "acronym": r.acronym,
                       "publisher": r.publisher, "homepage_url": r.homepage_url, "cfp_urls": r.cfp_urls,
                       "keywords": r.keywords, "questionable_evidence": r.questionable_evidence} for r in rows]}


class CandidateIn(BaseModel):
    registry_entry_id: uuid.UUID | None
    dedupe_key: str
    name: str
    acronym: str | None
    year: int | None
    official_url: str
    snapshot_artifact_id: uuid.UUID | None
    snapshot_hash: str | None
    tracks: list[str]
    deadlines: list[dict[str, Any]]
    location: str | None
    publisher: str | None
    total_score: float
    components: list[dict[str, Any]]
    excluded: bool
    exclusion_reason: str | None
    questionable_evidence: list[dict[str, Any]] = Field(default_factory=list)


class DiscoveryResultsIn(BaseModel):
    candidates: list[CandidateIn]
    failures: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/internal/projects/{project_id}/discovery/results")
async def discovery_results(project_id: uuid.UUID, body: DiscoveryResultsIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "conference_discovery")
    task_id = uuid.UUID(ctx.principal.scope["task_id"])
    existing = (await ctx.db.execute(select(ConferenceCandidate).where(ConferenceCandidate.task_id == task_id))).scalars().first()
    if existing:
        return {"replayed": True}
    for old in (await ctx.db.execute(select(ConferenceCandidate).where(ConferenceCandidate.project_id == project_id,
                                                                       ConferenceCandidate.is_current.is_(True)))).scalars():
        old.is_current = False
    # Deduplicate editions: keep the best-scoring candidate per dedupe key, merging track names.
    best: dict[str, CandidateIn] = {}
    for c in body.candidates:
        prev = best.get(c.dedupe_key)
        if prev is None or c.total_score > prev.total_score:
            if prev is not None:
                c.tracks = sorted(set(c.tracks) | set(prev.tracks))
            best[c.dedupe_key] = c
        else:
            prev.tracks = sorted(set(prev.tracks) | set(c.tracks))
    ordered = sorted(best.values(), key=lambda c: (c.excluded, -c.total_score, c.name))
    for i, c in enumerate(ordered, start=1):
        ctx.db.add(ConferenceCandidate(tenant_id=ctx.tenant_id, project_id=project_id, task_id=task_id, rank=i,
                                       **c.model_dump()))
    await audit(ctx.db, ctx.principal, "discovery.results", project_id=project_id,
                details={"candidates": len(ordered), "failures": body.failures})
    await ctx.db.commit()
    return {"candidates": len(ordered), "deduplicated_from": len(body.candidates)}


class MonitorResultIn(BaseModel):
    outcome: str = Field(pattern="^(not_modified|unchanged|changed|failed)$")
    url: str
    snapshot_id: uuid.UUID | None = None
    detail: str | None = None


@router.post("/internal/projects/{project_id}/cfp/monitor-result")
async def monitor_result(project_id: uuid.UUID, body: MonitorResultIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "cfp_monitor")
    project, _ = await project_for(ctx, project_id)
    ctx.db.add(CfpMonitorCheck(tenant_id=ctx.tenant_id, edition_id=project.target_edition_id, project_id=project_id,
                               task_id=uuid.UUID(ctx.principal.scope["task_id"]), url=body.url, outcome=body.outcome,
                               snapshot_id=body.snapshot_id, detail=body.detail))
    await ctx.db.commit()
    return {"recorded": True}


class TickIn(BaseModel):
    now: str | None = None


@router.post("/internal/projects/{project_id}/daily-tick")
async def daily_tick(project_id: uuid.UUID, body: TickIn, ctx: Ctx = Depends(service_ctx)):
    """Coordinator workflow's durable daily timer: schedule CFP monitoring and deadline reminders."""
    require_service_scope(ctx, project_id, "notifications.write")
    project, _ = await project_for(ctx, project_id)
    out: dict[str, Any] = {"monitor_task": None, "reminders": []}
    if project.state == "CANCELLED" or project.target_edition_id is None:
        return out
    last = (await ctx.db.execute(select(CfpMonitorCheck).where(CfpMonitorCheck.project_id == project_id)
                                 .order_by(CfpMonitorCheck.created_at.desc()))).scalars().first()
    if last is None or last.created_at < utcnow() - timedelta(hours=20):
        try:
            # Monitoring is created on behalf of the project owner (a system-initiated, non-billable check).
            owner_principal = ctx.principal
            t = await _create_monitor_task(Ctx(owner_principal, ctx.db, ctx.request), project)
            out["monitor_task"] = str(t.id)
        except ApiError as exc:
            out["monitor_skipped"] = exc.message
    now = utcnow()
    dls = list((await ctx.db.execute(select(DeadlineObligation).where(
        DeadlineObligation.edition_id == project.target_edition_id, DeadlineObligation.is_current.is_(True),
        DeadlineObligation.due_at.is_not(None), DeadlineObligation.due_at > now,
        (DeadlineObligation.track_id.is_(None)) | (DeadlineObligation.track_id == project.target_track_id)))).scalars())
    owners = (await ctx.db.execute(select(ProjectMember.user_id).where(
        ProjectMember.project_id == project_id, ProjectMember.removed_at.is_(None),
        (ProjectMember.role == "owner") | ProjectMember.is_corresponding_author.is_(True)))).scalars().all()
    for d in dls:
        days = (d.due_at - now).total_seconds() / 86400
        for window in (14, 7, 2):
            if days <= window:
                for uid in set(owners):
                    notify(ctx.db, tenant_id=project.tenant_id, user_id=uid, project_id=project_id, type="deadline.upcoming",
                           title=f"{project.title}: {d.deadline_kind.replace('_', ' ')} due in {max(int(days), 0)} days",
                           body=f"Due {d.due_at.isoformat()} UTC (stated timezone: {d.stated_timezone or 'not stated'}).",
                           link=f"/projects/{project_id}/cfp", dedupe_key=f"{project.tenant_id}:dl:{d.id}:{window}:{uid}")
                out["reminders"].append({"deadline": d.deadline_kind, "window_days": window})
                break
    await ctx.db.commit()
    return out


# --------------------------------------------------------------------------- operator registry curation
class RegistryIn(BaseModel):
    series_key: str = Field(min_length=2, max_length=200)
    name: str
    acronym: str | None = None
    organizer: str | None = None
    publisher: str | None = None
    homepage_url: str
    cfp_urls: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    verification_status: str = Field(default="unverified_seed", pattern="^(verified|unverified_seed|retired)$")
    questionable_evidence: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None


async def require_operator(ctx: Ctx) -> str:
    user = (await ctx.db.execute(select(User).where(User.id == ctx.principal.user_id))).scalar_one()
    if user.email not in get_settings().platform_operators:
        raise forbidden("platform operator role required")
    if not ctx.principal.mfa and get_settings().is_production:
        raise ApiError(403, "mfa_required", "registry curation requires multi-factor authentication")
    return user.email


@router.get("/registry")
async def list_registry(ctx: Ctx = Depends(user_ctx)):
    rows = (await ctx.db.execute(select(VenueRegistryEntry).order_by(VenueRegistryEntry.name))).scalars()
    return {"items": [{"id": str(r.id), "series_key": r.series_key, "name": r.name, "acronym": r.acronym,
                       "publisher": r.publisher, "homepage_url": r.homepage_url, "cfp_urls": r.cfp_urls,
                       "verification_status": r.verification_status, "verified_by": r.verified_by,
                       "verified_at": r.verified_at, "questionable_evidence": r.questionable_evidence,
                       "keywords": r.keywords} for r in rows]}


@router.put("/registry")
async def upsert_registry(body: RegistryIn, ctx: Ctx = Depends(user_ctx)):
    operator = await require_operator(ctx)
    for u in [body.homepage_url, *body.cfp_urls]:
        try:
            validate_url(u)
        except FetchBlocked as exc:
            raise unprocessable("url_not_permitted", f"{u}: {exc.reason}") from exc
    for ev in body.questionable_evidence:
        if not ev.get("source_url") or not ev.get("note"):
            raise unprocessable("evidence_required", "a venue concern must cite a source URL and a factual note")
    async with session_scope("ingest") as idb:
        row = (await idb.execute(select(VenueRegistryEntry).where(VenueRegistryEntry.series_key == body.series_key))).scalar_one_or_none()
        data = body.model_dump()
        if row is None:
            row = VenueRegistryEntry(**data)
            idb.add(row)
        else:
            for k, v in data.items():
                setattr(row, k, v)
        if body.verification_status == "verified":
            row.verified_by = operator
            row.verified_at = utcnow()
        await idb.commit()
        rid = row.id
    await audit(ctx.db, ctx.principal, "registry.upserted", resource_type="venue_registry", resource_id=rid,
                details={"series_key": body.series_key, "status": body.verification_status})
    await ctx.db.commit()
    return {"id": str(rid)}


_ = ConferenceEdition
