"""Test-only stage workflows (sandbox-safe module: non-workflow imports are passed through)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_research.api_client import ApiClient
    from rp_research.temporal_types import TaskInput, TaskOutcome
    from rp_research.workflows.base import run_task, transition

CRASHES: dict[str, int] = {}


# --------------------------------------------------------------------------- test-only stage workflow
@activity.defn
async def flaky_publish(task_id: str, project_id: str, mode: str) -> str:
    """mode=before_commit: crash after upload on attempt 1; mode=after_commit: crash after a successful commit."""
    attempt = activity.info().attempt
    async with ApiClient(task_id) as api:
        data = b'{"finding": "observed value recorded once"}'
        if mode == "before_commit" and attempt == 1:
            res = await api.request("POST", "/v1/internal/artifacts/reservations", json={
                "project_id": project_id, "task_id": task_id, "input_manifest_hash": "9" * 64,
                "output_kind": "generic_json", "media_type": "application/json"})
            await api.request("PUT", res["upload_url"], content=data)
            raise RuntimeError("simulated worker crash after upload, before commit")
        committed = await api.publish(project_id, "generic_json", data, "application/json", "9" * 64)
        if mode == "after_commit" and attempt == 1:
            raise RuntimeError("simulated crash after commit, before reporting")
        CRASHES[mode] = attempt
        return committed.artifact_id


@activity.defn
async def slow_step(task_id: str) -> str:
    for _ in range(600):
        activity.heartbeat()
        await asyncio.sleep(0.05)
    return "done"


@workflow.defn(name="FlakyPublishWorkflow")
class FlakyPublishWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            aid = await workflow.execute_activity(
                flaky_publish, args=[inp.task_id, inp.project_id, inp.params["mode"]],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(initial_interval=timedelta(milliseconds=100), maximum_attempts=3))
            if inp.params.get("advance"):
                await transition(inp, "TARGET_REVIEW", f"flaky-advance-{inp.task_id}", [aid])
                await transition(inp, "TARGET_REVIEW", f"flaky-advance-{inp.task_id}", [aid])  # duplicate delivery
            return TaskOutcome(state="succeeded", output_artifact_ids=[aid])
        return await run_task(inp, body)


@workflow.defn(name="SlowWorkflow")
class SlowWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            await workflow.execute_activity(slow_step, inp.task_id, start_to_close_timeout=timedelta(minutes=5),
                                            heartbeat_timeout=timedelta(seconds=10))
            return TaskOutcome(state="succeeded")
        return await run_task(inp, body)


