"""M9 workflow: execute an approved plan in the no-network sandbox, then independently recompute its metrics.

Execution is never retried automatically (a second execution is a new, visible run). The validator reads the raw
outputs back from immutable storage rather than trusting the runner's in-memory values.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from datetime import UTC, datetime, timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from rp_contracts.experiments import CENTS_PER_CPU_MINUTE, ExperimentPlanIn, rerun_command
    from rp_contracts.hashing import content_hash
    from rp_contracts.tasks import QUEUE_EXPERIMENT
    from rp_experiment.runner import execute
    from rp_experiment.validate import VALIDATOR_VERSION, recompute, reported_metrics

    from ..api_client import ApiCallError, ApiClient
    from ..registry import register
    from ..temporal_types import TaskInput, TaskOutcome
    from ..workflows.base import run_task
    from .common import app_error


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return buf.getvalue()


@activity.defn
async def experiment_execute(task_id: str, project_id: str, run_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            s = await api.get(f"/v1/internal/experiment-runs/{run_id}")
            if s["status"] not in ("queued", "running"):
                return {"status": s["status"], "replayed": True}
            if s["plan_status"] != "approved":
                await api.post(f"/v1/internal/experiment-runs/{run_id}/status",
                               {"status": "failed", "failure_reason": "the plan is not approved"})
                return {"status": "failed"}
            plan = ExperimentPlanIn.model_validate(s["spec"])
            code = await api.read_artifact_bytes(plan.code_artifact_id)
            problems = []
            if hashlib.sha256(code).hexdigest() != s["code_hash"]:
                problems.append("code bytes do not match the approved hash")
            inputs = {}
            for i in plan.inputs:
                data = await api.read_artifact_bytes(i.artifact_id)
                if hashlib.sha256(data).hexdigest() != s["input_hashes"].get(i.path):
                    problems.append(f"input {i.path} does not match the approved hash")
                inputs[i.path] = data
            if problems:
                await api.post(f"/v1/internal/experiment-runs/{run_id}/status",
                               {"status": "failed", "failure_reason": "; ".join(problems)})
                return {"status": "failed", "problems": problems}
            await api.post(f"/v1/internal/experiment-runs/{run_id}/status", {"status": "running"})
            started = datetime.now(UTC)
            out = execute(plan, s["image_ref"], code, inputs)
            finished = datetime.now(UTC)
            imh = content_hash({"run": run_id})
            log = await api.publish(project_id, "experiment_log", out.log.encode(), "text/plain", imh, slot=f"{run_id}:log",
                                    label=f"Run log {run_id[:8]}")
            raw = pred = None
            metrics, metrics_problem = (None, None)
            if out.outputs:
                raw = await api.publish(project_id, "experiment_raw_output", _zip(out.outputs), "application/zip", imh,
                                        slot=f"{run_id}:raw", label=f"Raw outputs {run_id[:8]}")
                if plan.predictions_path in out.outputs:
                    pred = await api.publish(project_id, "experiment_raw_output", out.outputs[plan.predictions_path],
                                             "text/csv", imh, slot=f"{run_id}:predictions", depends_on=[raw.artifact_id],
                                             label=f"Predictions {run_id[:8]}")
            status = out.status
            if status == "succeeded":
                metrics, metrics_problem = reported_metrics(out.outputs, plan)
                if metrics is None:
                    status = "failed"
            manifest = {
                "run_id": run_id, "plan_id": s["plan_id"], "run_type": plan.run_type, "image_ref": out.image,
                "argv": out.argv, "seed": plan.seed, "limits": plan.limits.model_dump(), "network": "none",
                "code_hash": s["code_hash"], "input_hashes": s["input_hashes"],
                "input_nature": {i.path: i.data_nature for i in plan.inputs}, "synthetic": s["synthetic"],
                "protocol": s["protocol"], "started_at": started.isoformat(), "finished_at": finished.isoformat(),
                "exit_code": out.exit_code, "duration_s": out.duration_s, "status": status,
                "environment": json.loads(out.environment) if out.environment else None,
                "outputs": {k: hashlib.sha256(v).hexdigest() for k, v in out.outputs.items()},
                "reported_metrics": metrics, "rerun_of": (s.get("rerun_of") or {}).get("run_id"),
                "rerun_command": rerun_command(s["plan_id"]),
            }
            rm = await api.publish_json(project_id, "run_manifest", manifest, imh, slot=f"{run_id}:manifest",
                                        depends_on=[s["plan_artifact_id"], log.artifact_id] + ([raw.artifact_id] if raw else []),
                                        label=f"Run manifest {run_id[:8]} ({status})")
            reason = None
            if status != "succeeded":
                reason = metrics_problem or {"timed_out": "the run exceeded its time limit",
                                             "sandbox_unavailable": "the sandbox was unavailable (fail closed)"}.get(
                    out.status, f"the program exited with code {out.exit_code}")
            await api.post(f"/v1/internal/experiment-runs/{run_id}/status", {
                "status": status, "exit_code": out.exit_code, "duration_s": out.duration_s,
                "run_manifest_artifact_id": rm.artifact_id, "raw_output_artifact_id": raw.artifact_id if raw else None,
                "predictions_artifact_id": pred.artifact_id if pred else None, "log_artifact_id": log.artifact_id,
                "reported_metrics": metrics, "failure_reason": reason})
            if out.duration_s:
                await api.record_usage(category="compute", provider="experiment_sandbox",
                                       units=out.duration_s * plan.limits.cpus, unit="cpu_seconds", stage="experiment_run",
                                       actual_cost_cents=max(1, math.ceil(out.duration_s * plan.limits.cpus / 60
                                                                          * CENTS_PER_CPU_MINUTE)))
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"status": status, "run_manifest_artifact_id": rm.artifact_id}


@activity.defn
async def experiment_validate(task_id: str, project_id: str, run_id: str) -> dict:
    async with ApiClient(task_id) as api:
        try:
            s = await api.get(f"/v1/internal/experiment-runs/{run_id}")
            plan = ExperimentPlanIn.model_validate(s["spec"])
            state = await api.get(f"/v1/internal/experiment-runs/{run_id}/outputs")
            if state["status"] != "succeeded" or not state["raw_output_artifact_id"]:
                report = {"status": "not_performed", "detail": f"run {state['status']}: nothing to recompute",
                          "validator": VALIDATOR_VERSION, "checks": []}
            else:
                raw = await api.read_artifact_bytes(state["raw_output_artifact_id"])
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    outputs = {n: z.read(n) for n in z.namelist()}
                report = recompute(plan, outputs, s["protocol"])
            art = await api.publish_json(project_id, "recomputation_report", report, content_hash({"recompute": run_id}),
                                         slot=f"{run_id}:recompute", label=f"Independent recomputation {run_id[:8]}")
            await api.post(f"/v1/internal/experiment-runs/{run_id}/recomputation", {"artifact_id": art.artifact_id,
                                                                                    "report": report})
        except ApiCallError as exc:
            raise app_error(exc) from exc
    return {"status": report["status"], "artifact_id": art.artifact_id}


NO_RETRY = RetryPolicy(maximum_attempts=1)
RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3)


@workflow.defn(name="ExperimentRunWorkflow")
class ExperimentRunWorkflow:
    @workflow.run
    async def run(self, inp: TaskInput) -> TaskOutcome:
        async def body() -> TaskOutcome:
            rid = inp.params["run_id"]
            ex = await workflow.execute_activity(experiment_execute, args=[inp.task_id, inp.project_id, rid],
                                                 task_queue=QUEUE_EXPERIMENT, start_to_close_timeout=timedelta(hours=2),
                                                 retry_policy=NO_RETRY)
            va = await workflow.execute_activity(experiment_validate, args=[inp.task_id, inp.project_id, rid],
                                                 task_queue=QUEUE_EXPERIMENT, start_to_close_timeout=timedelta(minutes=15),
                                                 retry_policy=RETRY)
            outs = [x for x in (ex.get("run_manifest_artifact_id"), va.get("artifact_id")) if x]
            # A failed run is a completed task with a visibly failed run record (diagnostics on the dashboard).
            return TaskOutcome(state="succeeded", output_artifact_ids=outs, result={"run": ex, "recomputation": va})
        return await run_task(inp, body)


register(QUEUE_EXPERIMENT, workflows=[ExperimentRunWorkflow], activities=[experiment_execute, experiment_validate])
