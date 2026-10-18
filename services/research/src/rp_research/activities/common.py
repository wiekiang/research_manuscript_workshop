"""Task lifecycle activities shared by every stage workflow. All I/O happens here, never in workflow code."""

from __future__ import annotations

from temporalio import activity
from temporalio.exceptions import ApplicationError

from ..api_client import ApiCallError, ApiClient
from ..temporal_types import TaskOutcome, TransitionAnswer, TransitionAsk


def to_app_error(exc: ApiCallError) -> ApplicationError:
    """Map API errors to Temporal retry semantics: 4xx (except 429) are not retryable."""
    retry_after = None
    if exc.status == 429 and isinstance(exc.details, dict):
        retry_after = exc.details.get("retry_after_seconds")
    from datetime import timedelta

    return ApplicationError(
        f"{exc.code}: {exc.message}", {"status": exc.status, "code": exc.code, "details": exc.details},
        type=exc.code, non_retryable=not exc.retryable,
        next_retry_delay=timedelta(seconds=int(retry_after)) if retry_after else None,
    )


@activity.defn
async def task_started(task_id: str) -> dict:
    info = activity.info()
    async with ApiClient(task_id) as api:
        try:
            task = await api.get_task()
            if task["state"] in ("succeeded", "cancelled", "failed_terminal"):
                return {"skip": True, "state": task["state"]}
            if task["state"] != "running":
                await api.update_task("running", attempt=info.attempt, progress={"workflow_run_id": info.workflow_run_id})
            return {"skip": False, "task": task}
        except ApiCallError as exc:
            raise to_app_error(exc) from exc


@activity.defn
async def task_finished(task_id: str, outcome: TaskOutcome) -> None:
    async with ApiClient(task_id) as api:
        try:
            await api.update_task(outcome.state, output_artifact_ids=outcome.output_artifact_ids or None,
                                  result=outcome.result or None, error_code=outcome.error_code,
                                  error_message=outcome.error_message, waiting_reason=outcome.waiting_reason)
        except ApiCallError as exc:
            if exc.code == "task_terminal":
                return
            raise to_app_error(exc) from exc


@activity.defn
async def task_progress(task_id: str, progress: dict) -> None:
    async with ApiClient(task_id) as api:
        try:
            await api.update_task("running", progress=progress)
        except ApiCallError as exc:
            raise to_app_error(exc) from exc


@activity.defn
async def project_runnable(task_id: str, project_id: str) -> str:
    """Return the project state so the workflow can wait while paused and stop when cancelled."""
    async with ApiClient(task_id) as api:
        try:
            return (await api.project(project_id))["state"]
        except ApiCallError as exc:
            raise to_app_error(exc) from exc


@activity.defn
async def request_transition(ask: TransitionAsk) -> TransitionAnswer:
    """Request (never apply) a canonical transition. On 409 stale, reload and retry against the new version only
    if the project is still in a state from which this request makes sense."""
    async with ApiClient(ask.task_id) as api:
        for _ in range(3):
            proj = await api.project(ask.project_id)
            if proj["state"] == ask.requested_state:
                return TransitionAnswer(False, proj["state"], proj["version"], "already in requested state")
            if ask.only_from_states and proj["state"] not in ask.only_from_states:
                return TransitionAnswer(False, proj["state"], proj["version"], f"project moved to {proj['state']}")
            try:
                res = await api.transition(ask.project_id, ask.requested_state, proj["version"], ask.idempotency_key,
                                           output_artifact_ids=ask.output_artifact_ids,
                                           input_manifest_hash=ask.input_manifest_hash,
                                           validator_result_ids=ask.validator_result_ids)
                return TransitionAnswer(True, res["state"], res["version"], "replayed" if res["replayed"] else "")
            except ApiCallError as exc:
                if exc.code == "stale_version":
                    continue
                if exc.code == "gate_unsatisfied":
                    return TransitionAnswer(False, proj["state"], proj["version"], f"gates not satisfied: {exc.details}")
                raise to_app_error(exc) from exc
        return TransitionAnswer(False, "", 0, "project kept changing; gave up after reloads")


@activity.defn
async def notify_approval_required(project_id: str, state: str, event_id: str) -> None:
    async with ApiClient(purpose="project", project_id=project_id) as api:
        try:
            await api.post(f"/v1/internal/projects/{project_id}/approval-required",
                           {"state": state, "event_id": event_id})
        except ApiCallError as exc:
            raise to_app_error(exc) from exc


@activity.defn
async def run_reconciler() -> dict:
    async with ApiClient(purpose="maintenance") as api:
        try:
            return await api.post("/v1/internal/maintenance/reconcile-artifacts", {})
        except ApiCallError as exc:
            raise to_app_error(exc) from exc


@activity.defn
async def project_daily_tick(project_id: str) -> dict:
    """Durable daily timer of the project coordinator: CFP monitoring and deadline reminders."""
    async with ApiClient(purpose="project", project_id=project_id) as api:
        try:
            return await api.post(f"/v1/internal/projects/{project_id}/daily-tick", {})
        except ApiCallError as exc:
            raise to_app_error(exc) from exc
