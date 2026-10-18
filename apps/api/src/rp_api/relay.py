"""Outbox relay: DB -> Temporal without a distributed transaction.

Polls undispatched outbox rows (system role, FOR UPDATE SKIP LOCKED) and:
  * task.requested     -> start the stage workflow with ID `task-{task_id}` (duplicate start = success)
  * project-scoped     -> signal-with-start `project-{project_id}` (the workflow deduplicates on event_id)
  * project.control    -> on cancel, also request cancellation of running task workflows
Failures back off exponentially and dead-letter after MAX_ATTEMPTS for operator replay.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from rp_contracts.tasks import QUEUE_RESEARCH, TASK_KINDS

from .config import get_settings
from .db.base import utcnow
from .db.engine import session_scope
from .db.models.core import OutboxEvent, WorkflowTask

log = logging.getLogger("rp_api.relay")
MAX_ATTEMPTS = 12
PROJECT_SIGNAL_TYPES = {"project.created", "state.changed", "approval.recorded", "approval.invalidated",
                        "rule.changed", "artifact.invalidated", "budget.threshold", "package.ready", "project.control",
                        "task.failed"}


class TemporalDispatcher:
    def __init__(self, client) -> None:
        self.client = client

    async def dispatch(self, ev: OutboxEvent) -> None:
        from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        env = ev.envelope
        if ev.event_type == "task.requested":
            payload = env.get("payload", {})
            spec = TASK_KINDS[payload["kind"]]
            try:
                await self.client.start_workflow(
                    spec.workflow,
                    {"task_id": env["task_id"], "project_id": env.get("project_id"), "kind": payload["kind"],
                     "params": payload.get("params", {}), "input_manifest_hash": env.get("input_manifest_hash")},
                    id=env["workflow_id"], task_queue=spec.task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    execution_timeout=timedelta(seconds=spec.timeout_seconds * max(spec.max_attempts, 1) + 3600),
                )
            except WorkflowAlreadyStartedError:
                pass
        if env.get("project_id") and ev.event_type in PROJECT_SIGNAL_TYPES:
            await self.client.start_workflow(
                "ProjectWorkflow", args=[env["project_id"], None], id=f"project-{env['project_id']}",
                task_queue=QUEUE_RESEARCH, start_signal="event", start_signal_args=[env],
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        if ev.event_type == "task.cancel_requested" and env.get("workflow_id"):
            try:
                await self.client.get_workflow_handle(env["workflow_id"]).cancel()
            except Exception as exc:  # noqa: BLE001
                log.info("cancel %s skipped: %s", env["workflow_id"], exc)
        if ev.event_type == "project.control" and env.get("payload", {}).get("action") == "cancel":
            async with session_scope("system") as db:
                running = (await db.execute(select(WorkflowTask.temporal_workflow_id).where(
                    WorkflowTask.project_id == ev.project_id, WorkflowTask.state.in_(["running", "queued"])))).scalars()
                for wid in running:
                    if wid:
                        try:
                            await self.client.get_workflow_handle(wid).cancel()
                        except Exception as exc:  # noqa: BLE001
                            log.info("cancel %s skipped: %s", wid, exc)


async def drain_once(dispatcher, batch: int = 50) -> int:
    """Dispatch one batch. Returns the number of events processed (dispatched or failed)."""
    n = 0
    async with session_scope("system") as db:
        rows = list((await db.execute(
            select(OutboxEvent).where(OutboxEvent.dispatched_at.is_(None), OutboxEvent.dead_lettered_at.is_(None),
                                      OutboxEvent.available_at <= utcnow())
            .order_by(OutboxEvent.created_at).limit(batch).with_for_update(skip_locked=True))).scalars())
        for ev in rows:
            n += 1
            try:
                await dispatcher.dispatch(ev)
                ev.dispatched_at = utcnow()
                ev.last_error = None
            except Exception as exc:  # noqa: BLE001
                ev.attempts += 1
                ev.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                if ev.attempts >= MAX_ATTEMPTS:
                    ev.dead_lettered_at = utcnow()
                    log.error("outbox event %s dead-lettered: %s", ev.event_id, ev.last_error)
                else:
                    ev.available_at = utcnow() + timedelta(seconds=min(2 ** ev.attempts, 600))
        await db.commit()
    return n


async def run_forever() -> None:
    from temporalio.client import Client

    s = get_settings()
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    dispatcher = TemporalDispatcher(client)
    log.info("outbox relay started")
    while True:
        try:
            n = await drain_once(dispatcher)
        except Exception as exc:  # noqa: BLE001
            log.exception("relay loop error: %s", exc)
            n = 0
        if n == 0:
            await asyncio.sleep(s.outbox_poll_interval_seconds)
