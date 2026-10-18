"""Shared task-workflow scaffolding.

Workflow code is deterministic: it only sequences activities, timers and signals. Each stage workflow calls
`run_task(inp, body)` which marks the task running, waits while the project is paused, stops when it is
cancelled, and always reports a final task state through the API.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from ..activities import common as acts
    from ..temporal_types import TaskInput, TaskOutcome, TransitionAnswer, TransitionAsk

DEFAULT_RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2.0,
                            maximum_interval=timedelta(minutes=2), maximum_attempts=5)
SHORT = timedelta(seconds=60)


def act_opts(timeout: timedelta = SHORT, retry: RetryPolicy = DEFAULT_RETRY) -> dict:
    return {"start_to_close_timeout": timeout, "retry_policy": retry}


async def wait_until_runnable(inp: TaskInput) -> bool:
    """Block (durably) while the project is paused/blocked. Returns False when cancelled."""
    if not inp.project_id:
        return True
    while True:
        state = await workflow.execute_activity(acts.project_runnable, args=[inp.task_id, inp.project_id], **act_opts())
        if state == "CANCELLED":
            return False
        if state not in ("PAUSED", "BLOCKED"):
            return True
        await workflow.sleep(timedelta(minutes=5))


async def transition(inp: TaskInput, requested_state: str, key: str, outputs: list[str] | None = None,
                     only_from: list[str] | None = None) -> TransitionAnswer:
    assert inp.project_id
    return await workflow.execute_activity(acts.request_transition, TransitionAsk(
        task_id=inp.task_id, project_id=inp.project_id, requested_state=requested_state, idempotency_key=key,
        output_artifact_ids=outputs or [], input_manifest_hash=inp.input_manifest_hash,
        only_from_states=only_from or []), **act_opts())


def _describe(exc: BaseException) -> tuple[str, str]:
    cause = exc.cause if isinstance(exc, ActivityError) and exc.cause else exc
    if isinstance(cause, ApplicationError):
        return cause.type or "activity_failed", str(cause.message)[:3000]
    return type(cause).__name__, str(cause)[:3000]


def _cancelled(exc: BaseException) -> bool:
    return isinstance(exc, (CancelledError, asyncio.CancelledError)) or (
        isinstance(exc, ActivityError) and isinstance(exc.cause, CancelledError))


async def run_task(inp: TaskInput, body: Callable[[], Awaitable[TaskOutcome]]) -> TaskOutcome:
    """Cancellation at any point (before, during or between activities) ends in a reported 'cancelled' state."""
    try:
        started = await workflow.execute_activity(acts.task_started, inp.task_id, **act_opts())
        if started.get("skip"):
            return TaskOutcome(state=started["state"])
        if not await wait_until_runnable(inp):
            outcome = TaskOutcome(state="cancelled", error_code="project_cancelled")
            await workflow.execute_activity(acts.task_finished, args=[inp.task_id, outcome], **act_opts())
            return outcome
        outcome = await body()
    except (CancelledError, asyncio.CancelledError, ActivityError, ApplicationError) as exc:
        if _cancelled(exc):
            outcome = TaskOutcome(state="cancelled", error_code="cancelled",
                                  error_message="cancelled by the researcher; partial artifacts remain labelled")
            await workflow.execute_activity(acts.task_finished, args=[inp.task_id, outcome], **act_opts(),
                                            cancellation_type=workflow.ActivityCancellationType.ABANDON)
            raise asyncio.CancelledError() from exc
        code, msg = _describe(exc)
        outcome = TaskOutcome(state="failed_terminal", error_code=code, error_message=msg)
    await workflow.execute_activity(acts.task_finished, args=[inp.task_id, outcome], **act_opts())
    return outcome
