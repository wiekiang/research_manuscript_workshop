"""Workflow task records. The API creates tasks and emits `task.requested`; the outbox relay starts the
Temporal workflow whose ID equals the task ID (so duplicate starts are idempotent)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import TERMINAL_TASK_STATES, TaskState
from rp_contracts.events import EventType
from rp_contracts.hashing import content_hash
from rp_contracts.tasks import TASK_KINDS

from ..db.base import utcnow
from ..db.models.core import Project, WorkflowTask
from ..errors import conflict, not_found, unprocessable
from ..security.tokens import Principal
from .common import audit, emit

ALLOWED_TASK_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.QUEUED: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.FAILED_TERMINAL},
    TaskState.RUNNING: {TaskState.SUCCEEDED, TaskState.FAILED_RETRYABLE, TaskState.FAILED_TERMINAL,
                        TaskState.WAITING_HUMAN, TaskState.CANCELLED},
    TaskState.FAILED_RETRYABLE: {TaskState.RUNNING, TaskState.FAILED_TERMINAL, TaskState.CANCELLED},
    TaskState.WAITING_HUMAN: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.SUCCEEDED, TaskState.FAILED_TERMINAL},
}


async def create_task(
    db: AsyncSession, actor: Principal, project: Project, kind: str, params: dict[str, Any], *,
    idempotency_key: str | None = None, input_manifest: Any = None, estimated_cost_cents: int | None = None,
) -> tuple[WorkflowTask, bool]:
    spec = TASK_KINDS.get(kind)
    if spec is None:
        raise unprocessable("unknown_task_kind", f"unknown task kind {kind}")
    imh = content_hash(input_manifest if input_manifest is not None else {"kind": kind, "params": params})
    key = idempotency_key or f"{kind}:{project.id}:{imh}"
    existing = (await db.execute(select(WorkflowTask).where(
        WorkflowTask.tenant_id == project.tenant_id, WorkflowTask.idempotency_key == key))).scalar_one_or_none()
    if existing is not None:
        return existing, False
    task = WorkflowTask(
        id=uuid.uuid4(), tenant_id=project.tenant_id, project_id=project.id, kind=kind, state=TaskState.QUEUED,
        attempt=0, max_attempts=spec.max_attempts, timeout_seconds=spec.timeout_seconds, idempotency_key=key,
        input_manifest_hash=imh, params=params, requested_by=actor.actor_id, compensation=spec.compensation,
        owner_label=spec.owner_label, estimated_cost_cents=estimated_cost_cents,
    )
    task.temporal_workflow_id = f"task-{task.id}"
    db.add(task)
    await db.flush()
    emit(db, tenant_id=project.tenant_id, type=EventType.TASK_REQUESTED, actor_type=actor.actor_type,
         actor_id=actor.actor_id, project_id=project.id, task_id=task.id, workflow_id=task.temporal_workflow_id,
         input_manifest_hash=imh, payload={"kind": kind, "params": params, "workflow": spec.workflow,
                                           "task_queue": spec.task_queue})
    await audit(db, actor, "task.requested", tenant_id=project.tenant_id, project_id=project.id,
                resource_type="workflow_task", resource_id=task.id, details={"kind": kind})
    return task, True


async def get_task(db: AsyncSession, task_id: uuid.UUID, lock: bool = False) -> WorkflowTask:
    q = select(WorkflowTask).where(WorkflowTask.id == task_id)
    if lock:
        q = q.with_for_update()
    t = (await db.execute(q)).scalar_one_or_none()
    if t is None:
        raise not_found("task")
    return t


async def update_task(
    db: AsyncSession, actor: Principal, task: WorkflowTask, new_state: TaskState, *, attempt: int | None = None,
    error_code: str | None = None, error_message: str | None = None, waiting_reason: str | None = None,
    output_artifact_ids: list[uuid.UUID] | None = None, result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
) -> WorkflowTask:
    cur = TaskState(task.state)
    if cur == new_state and new_state == TaskState.RUNNING:
        if progress:
            task.progress = {**(task.progress or {}), **progress}
        return task
    if cur in TERMINAL_TASK_STATES:
        if cur == new_state:
            return task  # duplicate terminal report: idempotent
        raise conflict("task_terminal", f"task already {cur}")
    if new_state not in ALLOWED_TASK_TRANSITIONS.get(cur, set()):
        raise conflict("invalid_task_transition", f"{cur} -> {new_state} is not allowed")
    task.state = new_state
    if attempt is not None:
        task.attempt = attempt
    now = utcnow()
    if new_state == TaskState.RUNNING and task.started_at is None:
        task.started_at = now
    if new_state in TERMINAL_TASK_STATES:
        task.finished_at = now
    task.error_code = error_code
    task.error_message = error_message
    task.waiting_reason = waiting_reason
    if output_artifact_ids is not None:
        task.output_artifact_ids = output_artifact_ids
    if result is not None:
        task.result = result
    if progress:
        task.progress = {**(task.progress or {}), **progress}
    etype = EventType.TASK_FAILED if new_state in {TaskState.FAILED_TERMINAL, TaskState.FAILED_RETRYABLE} else EventType.TASK_UPDATED
    emit(db, tenant_id=task.tenant_id, type=etype, actor_type=actor.actor_type, actor_id=actor.actor_id,
         project_id=task.project_id, task_id=task.id, output_artifact_ids=output_artifact_ids or [],
         payload={"kind": task.kind, "state": new_state.value, "error_code": error_code, "waiting_reason": waiting_reason})
    return task
