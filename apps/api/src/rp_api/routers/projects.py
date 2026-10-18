from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from rp_contracts.copy import RESPONSIBILITY_MESSAGE, RESPONSIBILITY_VERSION
from rp_contracts.enums import ApprovalStatus, ProjectRole, ProjectState, TaskState
from rp_contracts.events import EventType
from rp_contracts.state_machine import FORWARD_RULES, OVERLAYS
from rp_contracts.tasks import TASK_KINDS

from ..config import get_settings
from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.core import (
    Approval,
    Membership,
    Project,
    ProjectEvent,
    ProjectMember,
    User,
    WorkflowTask,
)
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..services import budget as budget_svc
from ..services import gates as gate_registry
from ..services.approvals import DECLARATIONS
from ..services.common import audit, emit, idempotency_lookup, idempotency_store
from ..services.transitions import TransitionRequest, append_event, request_transition

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    topic: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=20000)
    budget_cap_cents: int | None = Field(default=None, ge=0, le=10_000_000)
    responsibility_acknowledged: bool = False


class ControlIn(BaseModel):
    expected_version: int
    reason: str | None = Field(default=None, max_length=2000)


class AdvanceIn(BaseModel):
    requested_state: ProjectState
    expected_version: int


class MemberIn(BaseModel):
    email: EmailStr
    role: ProjectRole
    is_corresponding_author: bool = False


class MemberPatch(BaseModel):
    role: ProjectRole | None = None
    is_corresponding_author: bool | None = None


def project_out(p: Project, role: str | None = None, extra: dict | None = None) -> dict[str, Any]:
    return {
        "id": str(p.id), "title": p.title, "topic": p.topic, "description": p.description, "state": p.state,
        "resume_state": p.resume_state, "overlay_reason": p.overlay_reason, "version": p.version,
        "readiness_stage": p.readiness_stage, "target_mode": p.target_mode,
        "target_track_id": str(p.target_track_id) if p.target_track_id else None,
        "target_edition_id": str(p.target_edition_id) if p.target_edition_id else None,
        "method_instance_id": str(p.method_instance_id) if p.method_instance_id else None,
        "budget_cap_cents": p.budget_cap_cents, "currency": p.currency, "my_role": role,
        "created_at": p.created_at, "updated_at": p.updated_at, **(extra or {}),
    }


async def next_step(ctx: Ctx, project: Project) -> dict[str, Any] | None:
    """Explain what is needed to leave the current state (dashboard "what is needed next")."""
    state = ProjectState(project.state)
    if state in OVERLAYS:
        return {"target_state": project.resume_state, "overlay": state.value,
                "message": f"Project is {state.value.lower()}" + (f": {project.overlay_reason}" if project.overlay_reason else ""),
                "gates": []}
    rule = next((r for r in FORWARD_RULES if r.source == state), None)
    if rule is None:
        return None
    results = await gate_registry.evaluate_all(ctx.db, project, rule.gates)
    return {"target_state": rule.target.value, "description": rule.description,
            "gates": [r.as_dict() for r in results], "ready": all(r.passed for r in results)}


@router.post("", status_code=201)
async def create_project(body: ProjectIn, ctx: Ctx = Depends(user_ctx),
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    scope = "POST /projects"
    prior = await idempotency_lookup(ctx.db, ctx.tenant_id, scope, idempotency_key, body.model_dump(mode="json"))
    if prior:
        return prior.response
    user = (await ctx.db.execute(select(User).where(User.id == ctx.principal.user_id))).scalar_one()
    if not body.responsibility_acknowledged:
        raise unprocessable("responsibility_ack_required",
                            "acknowledge the researcher responsibility message to create a project",
                            {"message": RESPONSIBILITY_MESSAGE, "version": RESPONSIBILITY_VERSION})
    now = utcnow()
    if user.responsibility_ack_version != RESPONSIBILITY_VERSION:
        user.responsibility_ack_at = now
        user.responsibility_ack_version = RESPONSIBILITY_VERSION
    project = Project(
        id=uuid.uuid4(), tenant_id=ctx.tenant_id, title=body.title.strip(), topic=body.topic,
        description=body.description, state=ProjectState.CREATED, owner_id=user.id,
        budget_cap_cents=body.budget_cap_cents if body.budget_cap_cents is not None else get_settings().default_project_budget_cents,
        currency=get_settings().default_currency, responsibility_notice_shown_at=now,
    )
    ctx.db.add(project)
    await ctx.db.flush()
    ctx.db.add(ProjectMember(tenant_id=ctx.tenant_id, project_id=project.id, user_id=user.id, role=ProjectRole.OWNER,
                             is_corresponding_author=True, added_by=user.id))
    await append_event(ctx.db, project, ctx.principal, "project.created", to_state=project.state,
                       payload={"responsibility_version": RESPONSIBILITY_VERSION})
    emit(ctx.db, tenant_id=ctx.tenant_id, type=EventType.PROJECT_CREATED, actor_type="user", actor_id=ctx.principal.actor_id,
         project_id=project.id, payload={"title": project.title})
    await audit(ctx.db, ctx.principal, "project.created", project_id=project.id, resource_type="project",
                resource_id=project.id, details={"responsibility_notice": RESPONSIBILITY_VERSION})
    out = project_out(project, ProjectRole.OWNER.value)
    out_json = json.loads(json.dumps(out, default=str))
    idempotency_store(ctx.db, ctx.tenant_id, scope, idempotency_key, ctx.principal.actor_id, body.model_dump(mode="json"),
                      201, out_json)
    await ctx.db.commit()
    return out_json


@router.get("")
async def list_projects(ctx: Ctx = Depends(user_ctx), cursor: str | None = None, limit: int = Query(25, le=100)):
    q = (select(Project, ProjectMember.role).join(ProjectMember, ProjectMember.project_id == Project.id)
         .where(ProjectMember.user_id == ctx.principal.user_id, ProjectMember.removed_at.is_(None),
                Project.deleted_at.is_(None)).order_by(Project.updated_at.desc(), Project.id))
    if cursor:
        try:
            ts, pid = cursor.split("|")
            q = q.where((Project.updated_at < ts) | ((Project.updated_at == ts) & (Project.id > uuid.UUID(pid))))
        except ValueError as exc:
            raise unprocessable("invalid_cursor", "malformed cursor") from exc
    rows = (await ctx.db.execute(q.limit(limit + 1))).all()
    items = []
    for p, role in rows[:limit]:
        waiting = (await ctx.db.execute(select(func.count()).select_from(WorkflowTask).where(
            WorkflowTask.project_id == p.id, WorkflowTask.state == TaskState.WAITING_HUMAN))).scalar_one()
        items.append(project_out(p, role, {"next_step": await next_step(ctx, p), "waiting_human_tasks": waiting}))
    nxt = None
    if len(rows) > limit:
        last = rows[limit - 1][0]
        nxt = f"{last.updated_at.isoformat()}|{last.id}"
    return {"items": items, "next_cursor": nxt}


@router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, role = await project_for(ctx, project_id, allow_admin_read=True)
    approvals = list((await ctx.db.execute(select(Approval).where(Approval.project_id == project.id)
                                           .order_by(Approval.decided_at.desc()))).scalars())
    gates = {}
    for a in approvals:
        gates.setdefault(a.gate, {"gate": a.gate, "status": a.status, "approval_id": str(a.id), "decided_at": a.decided_at,
                                  "invalidation_reason": a.invalidation_reason})
    tasks_waiting = (await ctx.db.execute(select(WorkflowTask).where(
        WorkflowTask.project_id == project.id, WorkflowTask.state == TaskState.WAITING_HUMAN))).scalars().all()
    budget = await budget_svc.status(ctx.db, project)
    return project_out(project, role, {
        "next_step": await next_step(ctx, project),
        "approvals": list(gates.values()),
        "waiting_human_tasks": [{"id": str(t.id), "kind": t.kind, "reason": t.waiting_reason} for t in tasks_waiting],
        "budget": budget.as_dict(),
        "responsibility_message": RESPONSIBILITY_MESSAGE,
    })


@router.get("/{project_id}/events")
async def project_events(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), after_seq: int = 0,
                         limit: int = Query(100, le=500)):
    await project_for(ctx, project_id, allow_admin_read=True)
    rows = (await ctx.db.execute(select(ProjectEvent).where(ProjectEvent.project_id == project_id,
                                                            ProjectEvent.seq > after_seq)
                                 .order_by(ProjectEvent.seq).limit(limit))).scalars()
    return {"items": [event_out(e) for e in rows]}


def event_out(e: ProjectEvent) -> dict[str, Any]:
    return {"id": str(e.id), "seq": e.seq, "type": e.event_type, "from_state": e.from_state, "to_state": e.to_state,
            "version": e.resulting_version, "actor_type": e.actor_type, "actor_id": e.actor_id,
            "occurred_at": e.occurred_at, "payload": e.payload, "gate_results": e.gate_results,
            "output_artifact_ids": [str(i) for i in e.output_artifact_ids or []],
            "human_approval_id": str(e.human_approval_id) if e.human_approval_id else None}


@router.get("/{project_id}/tasks")
async def project_tasks(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), limit: int = Query(50, le=200)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(WorkflowTask).where(WorkflowTask.project_id == project_id)
                                 .order_by(WorkflowTask.created_at.desc()).limit(limit))).scalars()
    return {"items": [task_out(t) for t in rows]}


async def _task(ctx: Ctx, project_id: uuid.UUID, task_id: uuid.UUID) -> WorkflowTask:
    t = (await ctx.db.execute(select(WorkflowTask).where(WorkflowTask.id == task_id, WorkflowTask.project_id == project_id)
                              .with_for_update())).scalar_one_or_none()
    if t is None:
        raise not_found("task")
    return t


@router.post("/{project_id}/tasks/{task_id}/cancel", status_code=202)
async def cancel_task(project_id: uuid.UUID, task_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Request cancellation of one queued/running task; Temporal runs its compensation. Committed artifacts are kept."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    t = await _task(ctx, project_id, task_id)
    if t.state not in (TaskState.QUEUED, TaskState.RUNNING, TaskState.WAITING_HUMAN):
        raise conflict("not_cancellable", f"task is {t.state}")
    emit(ctx.db, tenant_id=ctx.tenant_id, type=EventType.TASK_CANCEL_REQUESTED, actor_type=ctx.principal.actor_type,
         actor_id=ctx.principal.actor_id, project_id=project_id, task_id=t.id, workflow_id=t.temporal_workflow_id,
         payload={"kind": t.kind})
    await audit(ctx.db, ctx.principal, "task.cancel_requested", tenant_id=ctx.tenant_id, project_id=project_id,
                resource_type="workflow_task", resource_id=t.id)
    await ctx.db.commit()
    return task_out(t)


class RetryIn(BaseModel):
    confirm_cost: bool = False


@router.post("/{project_id}/tasks/{task_id}/retry", status_code=202)
async def retry_task(project_id: uuid.UUID, task_id: uuid.UUID, body: RetryIn, ctx: Ctx = Depends(user_ctx)):
    """Re-run a failed or cancelled task from its recorded, versioned inputs as a new task (history is kept)."""
    from rp_contracts.tasks import TASK_KINDS

    from ..services.tasks import create_task

    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    t = await _task(ctx, project_id, task_id)
    if t.state not in (TaskState.FAILED_TERMINAL, TaskState.CANCELLED):
        raise conflict("not_retryable", f"only failed or cancelled tasks can be retried (task is {t.state})")
    if TASK_KINDS[t.kind].billable and not body.confirm_cost:
        raise unprocessable("cost_confirmation_required", "this task can incur model or compute cost; confirm to retry",
                            {"estimated_cost_cents": t.estimated_cost_cents})
    n = (await ctx.db.execute(select(func.count()).select_from(WorkflowTask).where(
        WorkflowTask.idempotency_key.like(f"retry:{t.id}:%")))).scalar_one()
    new, _ = await create_task(ctx.db, ctx.principal, project, t.kind, t.params, idempotency_key=f"retry:{t.id}:{n + 1}",
                               estimated_cost_cents=t.estimated_cost_cents)
    new.input_manifest_hash = t.input_manifest_hash
    await ctx.db.commit()
    return task_out(new)


def task_out(t: WorkflowTask) -> dict[str, Any]:
    return {"id": str(t.id), "kind": t.kind, "state": t.state, "attempt": t.attempt, "max_attempts": t.max_attempts,
            "owner": t.owner_label, "error_code": t.error_code, "error_message": t.error_message,
            "waiting_reason": t.waiting_reason, "progress": t.progress, "result": t.result,
            "output_artifact_ids": [str(i) for i in t.output_artifact_ids or []], "created_at": t.created_at,
            "updated_at": t.updated_at, "started_at": t.started_at, "finished_at": t.finished_at,
            "estimated_cost_cents": t.estimated_cost_cents, "params": t.params,
            "billable": TASK_KINDS[t.kind].billable if t.kind in TASK_KINDS else None}


@router.post("/{project_id}/advance")
async def advance(project_id: uuid.UUID, body: AdvanceIn, ctx: Ctx = Depends(user_ctx),
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    await project_for(ctx, project_id, OWNER_ONLY)
    res = await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
        requested_state=body.requested_state, expected_project_version=body.expected_version,
        idempotency_key=idempotency_key or f"user-advance:{uuid.uuid4()}"))
    await ctx.db.commit()
    return res.as_dict()


async def _control(ctx: Ctx, project_id: uuid.UUID, target: ProjectState | None, body: ControlIn, action: str):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    if action == "resume":
        if project.state not in {s.value for s in OVERLAYS} or project.resume_state is None:
            raise conflict("not_paused", "project is not paused or blocked")
        target = ProjectState(project.resume_state)
    assert target is not None
    res = await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
        requested_state=target, expected_project_version=body.expected_version,
        idempotency_key=f"{action}:{project_id}:{body.expected_version}", reason=body.reason, cause="control"))
    if action == "cancel":
        queued = (await ctx.db.execute(select(WorkflowTask).where(
            WorkflowTask.project_id == project_id, WorkflowTask.state.in_([TaskState.QUEUED, TaskState.WAITING_HUMAN,
                                                                           TaskState.FAILED_RETRYABLE])))).scalars()
        for t in queued:
            t.state = TaskState.CANCELLED
            t.finished_at = utcnow()
    emit(ctx.db, tenant_id=ctx.tenant_id, type=EventType.PROJECT_CONTROL, actor_type="user",
         actor_id=ctx.principal.actor_id, project_id=project_id, payload={"action": action, "reason": body.reason})
    await ctx.db.commit()
    return res.as_dict()


@router.post("/{project_id}/pause")
async def pause(project_id: uuid.UUID, body: ControlIn, ctx: Ctx = Depends(user_ctx)):
    return await _control(ctx, project_id, ProjectState.PAUSED, body, "pause")


@router.post("/{project_id}/resume")
async def resume(project_id: uuid.UUID, body: ControlIn, ctx: Ctx = Depends(user_ctx)):
    return await _control(ctx, project_id, None, body, "resume")


@router.post("/{project_id}/cancel")
async def cancel(project_id: uuid.UUID, body: ControlIn, ctx: Ctx = Depends(user_ctx)):
    return await _control(ctx, project_id, ProjectState.CANCELLED, body, "cancel")


# --------------------------------------------------------------------------- members
@router.get("/{project_id}/members")
async def members(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, allow_admin_read=True)
    rows = (await ctx.db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(
        ProjectMember.project_id == project_id, ProjectMember.removed_at.is_(None)))).all()
    return [{"user_id": str(u.id), "email": u.email, "display_name": u.display_name, "role": m.role,
             "is_corresponding_author": m.is_corresponding_author} for m, u in rows]


@router.post("/{project_id}/members", status_code=201)
async def add_member(project_id: uuid.UUID, body: MemberIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    async with session_scope("system") as sdb:
        user = (await sdb.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None:
        raise not_found("account")
    member_of_ws = (await ctx.db.execute(select(Membership).where(
        Membership.tenant_id == ctx.tenant_id, Membership.user_id == user.id, Membership.status == "active"))).scalar_one_or_none()
    if member_of_ws is None:
        raise unprocessable("not_workspace_member", "add the person to this workspace first")
    existing = (await ctx.db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                                 ProjectMember.user_id == user.id))).scalar_one_or_none()
    if existing:
        existing.role = body.role
        existing.removed_at = None
        existing.is_corresponding_author = body.is_corresponding_author
    else:
        ctx.db.add(ProjectMember(tenant_id=ctx.tenant_id, project_id=project_id, user_id=user.id, role=body.role,
                                 is_corresponding_author=body.is_corresponding_author, added_by=ctx.principal.user_id))
    if body.is_corresponding_author:
        await _single_corresponding(ctx, project_id, user.id)
    await audit(ctx.db, ctx.principal, "project.member_added", project_id=project_id, resource_type="user",
                resource_id=user.id, details={"role": body.role.value})
    await ctx.db.commit()
    return {"user_id": str(user.id), "role": body.role.value}


async def _single_corresponding(ctx: Ctx, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    for m in (await ctx.db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id))).scalars():
        m.is_corresponding_author = m.user_id == user_id


@router.patch("/{project_id}/members/{user_id}")
async def patch_member(project_id: uuid.UUID, user_id: uuid.UUID, body: MemberPatch, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    m = (await ctx.db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                          ProjectMember.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise not_found("member")
    if body.role is not None:
        if user_id == ctx.principal.user_id and body.role != ProjectRole.OWNER:
            raise unprocessable("owner_required", "a project must keep its owner")
        m.role = body.role
    if body.is_corresponding_author:
        await _single_corresponding(ctx, project_id, user_id)
    await audit(ctx.db, ctx.principal, "project.member_updated", project_id=project_id, resource_type="user",
                resource_id=user_id, details=body.model_dump(mode="json", exclude_none=True))
    await ctx.db.commit()
    return {"user_id": str(user_id), "role": m.role, "is_corresponding_author": m.is_corresponding_author}


# --------------------------------------------------------------------------- approvals (read side)
@router.get("/{project_id}/approvals")
async def approvals(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(Approval, User).join(User, User.id == Approval.approver_id).where(
        Approval.project_id == project_id).order_by(Approval.decided_at.desc()))).all()
    return {
        "declarations": {g.value: {"version": d.version, "text": d.text, "approver": d.approver} for g, d in DECLARATIONS.items()},
        "items": [{"id": str(a.id), "gate": a.gate, "status": a.status, "approver": u.display_name,
                   "approver_role": a.approver_role, "declaration_version": a.declaration_version,
                   "rationale": a.rationale, "content_manifest_hash": a.content_manifest_hash,
                   "bound_artifacts": a.bound_artifacts, "decided_at": a.decided_at,
                   "invalidated_at": a.invalidated_at, "invalidation_reason": a.invalidation_reason,
                   "is_current": a.status == ApprovalStatus.VALID} for a, u in rows],
    }


# --------------------------------------------------------------------------- live status (SSE)
@router.get("/{project_id}/stream")
async def stream(project_id: uuid.UUID, request: Request, ctx: Ctx = Depends(user_ctx),
                 last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    await project_for(ctx, project_id, allow_admin_read=True)
    tenant_id, user_id = ctx.tenant_id, ctx.principal.user_id
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def gen():
        seq = start
        last_task_marker = None
        ticks = 0
        while not await request.is_disconnected() and ticks < 3600:
            ticks += 1
            async with session_scope("app", tenant_id=tenant_id, user_id=user_id) as db:
                rows = list((await db.execute(select(ProjectEvent).where(
                    ProjectEvent.project_id == project_id, ProjectEvent.seq > seq).order_by(ProjectEvent.seq).limit(50))).scalars())
                marker = (await db.execute(select(WorkflowTask.updated_at).where(
                    WorkflowTask.project_id == project_id).order_by(WorkflowTask.updated_at.desc()).limit(1))).scalar()
            for e in rows:
                seq = e.seq
                yield f"id: {e.seq}\nevent: project\ndata: {json.dumps(event_out(e), default=str)}\n\n"
            if marker != last_task_marker:
                last_task_marker = marker
                yield f"event: tasks\ndata: {json.dumps({'updated_at': marker}, default=str)}\n\n"
            if ticks % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store",
                                                                              "X-Accel-Buffering": "no"})


def _unused() -> None:  # keep imports referenced for static analysis
    _ = (ApiError, EDIT_ROLES)
