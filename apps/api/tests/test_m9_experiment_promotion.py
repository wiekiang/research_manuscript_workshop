"""M9 promotion guard: a failed, timed-out or unrecomputable run stays recorded and visible but can never become a
result (see the module docstring of rp_api.features.experiments)."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from conftest import make_project, make_task, make_user, service_token

RUN_PATH = "/v1/internal/experiment-runs/{run_id}"
SPEC = {"title": "Restoration classifier on eight pipelines", "code_artifact_id": str(uuid.uuid4()), "code_path": "main.py",
        "entrypoint": ["python", "main.py", "--seed", "{seed}"],
        "inputs": [{"artifact_id": str(uuid.uuid4()), "path": "data/labels.csv", "data_nature": "empirical"}],
        "image": "python-sci:1", "seed": 7, "limits": {"cpus": 1, "memory_mb": 512, "timeout_s": 60},
        "run_type": "confirmatory", "metrics": [{"name": "accuracy"}], "tolerance": 1e-9, "sample_size": 8,
        "data_origin": "eight public R pipelines", "data_rights": "public source code (MIT/GPL)",
        "limitations": "small exploratory sample"}


async def seed_run(u, project_id: str) -> tuple[str, str, dict]:
    """An approved plan with one queued run, as `start_run` leaves it; returns (run_id, task_id, worker headers)."""
    from rp_api.db.engine import session_scope
    from rp_api.db.models.experiment import ExperimentPlan, ExperimentRun

    run_id = uuid.uuid4()
    task_id = await make_task(u.tenant_id, project_id, kind="experiment_run", params={"run_id": str(run_id)})
    async with session_scope("system") as db:
        plan = ExperimentPlan(tenant_id=uuid.UUID(u.tenant_id), project_id=uuid.UUID(project_id),
                              method_instance_id=uuid.uuid4(), protocol_id=uuid.uuid4(), protocol_hash="a" * 64,
                              plan_number=1, title=SPEC["title"], spec=SPEC, image_ref="python-sci@sha256:" + "b" * 64,
                              code_hash="c" * 64, input_hashes={"data/labels.csv": "d" * 64}, run_type="confirmatory",
                              estimate_cents=10, status="approved", artifact_id=uuid.uuid4(),
                              approved_by=uuid.UUID(u.user_id))
        db.add(plan)
        await db.flush()
        db.add(ExperimentRun(id=run_id, tenant_id=plan.tenant_id, project_id=plan.project_id, plan_id=plan.id,
                             task_id=uuid.UUID(task_id)))
        await db.commit()
    return str(run_id), task_id, await service_token(u.client, task_id)


async def commit_json_artifact(client, h, project_id: str, task_id: str, kind: str, payload: dict) -> str:
    data = json.dumps(payload, sort_keys=True).encode()
    r = await client.post("/v1/internal/artifacts/reservations", headers=h, json={
        "project_id": project_id, "task_id": task_id, "input_manifest_hash": "e" * 64, "output_kind": kind,
        "media_type": "application/json", "slot": f"{kind}:{uuid.uuid4().hex[:8]}"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert (await client.put(res["upload_url"], content=data, headers=h)).status_code == 200
    r = await client.post(f"/v1/internal/artifacts/{res['reservation_id']}/commit", headers=h,
                          json={"content_hash": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
    assert r.status_code == 200, r.text
    return r.json()["artifact_id"]


async def visible_run(u, project_id: str, run_id: str) -> dict:
    r = await u.get(f"/v1/projects/{project_id}/experiments")
    assert r.status_code == 200, r.text
    return next(x for p in r.json()["items"] for x in p["runs"] if x["id"] == run_id)


async def assert_not_a_result(u, project_id: str, run: dict) -> None:
    assert run["promotable"] is False and run["result_manifest_id"] is None
    r = await u.get(f"/v1/projects/{project_id}/results")
    assert r.status_code == 200, r.text
    assert r.json()["items"] == [], "a refused promotion must not leave a result behind"


@pytest.mark.parametrize("status", ["failed", "timed_out", "sandbox_unavailable"])
async def test_failed_run_is_recorded_but_never_promoted(client, status):
    u = await make_user(client)
    p = await make_project(u)
    run_id, _, h = await seed_run(u, p["id"])

    # The worker reports the terminal failure exactly as the sandbox saw it.
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/status", headers=h, json={
        "status": status, "exit_code": 1, "duration_s": 3.5, "failure_reason": f"sandbox reported {status}",
        "reported_metrics": {"accuracy": 0.99}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == status and r.json()["reported_metrics"] is None, "a failed run carries no metrics"

    r = await u.post(f"/v1/experiment-runs/{run_id}/promote")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "run_not_succeeded"

    run = await visible_run(u, p["id"], run_id)
    assert run["status"] == status, run
    assert run["failure_reason"] == f"sandbox reported {status}" and run["exit_code"] == 1 and run["duration_s"] == 3.5
    assert run["reported_metrics"] is None and run["recomputation"] is None
    await assert_not_a_result(u, p["id"], run)

    # The refused promotion did not disturb the record: a later worker retry still cannot rewrite it.
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/status", headers=h,
                          json={"status": "succeeded", "reported_metrics": {"accuracy": 0.75}})
    assert r.status_code == 200 and r.json()["status"] == status, "terminal states never change"
    assert (await u.post(f"/v1/experiment-runs/{run_id}/promote")).json()["error"]["code"] == "run_not_succeeded"


async def test_run_whose_metrics_could_not_be_recomputed_is_never_promoted(client):
    u = await make_user(client)
    p = await make_project(u)
    run_id, task_id, h = await seed_run(u, p["id"])

    r = await client.post(RUN_PATH.format(run_id=run_id) + "/status", headers=h, json={
        "status": "succeeded", "exit_code": 0, "duration_s": 12.0, "reported_metrics": {"accuracy": 0.99}})
    assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text

    # Before the validator has spoken there is nothing to promote.
    r = await u.post(f"/v1/experiment-runs/{run_id}/promote")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_recomputed", r.text

    # The independent validator recomputes from the raw predictions and disagrees with the reported value.
    report = {"status": "failed", "validator": "rp-experiment-validator/0.1",
              "checks": [{"id": "recompute:accuracy", "passed": False,
                          "evidence": {"reported": 0.99, "recomputed": 0.75, "n": 8, "tolerance": 1e-9}}],
              "summary": "reported accuracy 0.99 disagrees with recomputed 0.75"}
    art = await commit_json_artifact(client, h, p["id"], task_id, "recomputation_report", report)
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/recomputation", headers=h,
                          json={"artifact_id": art, "report": report})
    assert r.status_code == 200, r.text
    assert r.json()["recomputation"]["status"] == "failed" and r.json()["promotable"] is False

    r = await u.post(f"/v1/experiment-runs/{run_id}/promote")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "not_recomputed"

    run = await visible_run(u, p["id"], run_id)
    assert run["status"] == "succeeded" and run["reported_metrics"] == {"accuracy": 0.99}
    assert run["recomputation"] == report and run["recomputation_artifact_id"] == art
    await assert_not_a_result(u, p["id"], run)

    # The verdict is immutable: a second, friendlier report cannot replace the recorded failure.
    passed = {**report, "status": "passed"}
    art2 = await commit_json_artifact(client, h, p["id"], task_id, "recomputation_report", passed)
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/recomputation", headers=h,
                          json={"artifact_id": art2, "report": passed})
    assert r.status_code == 200 and r.json()["recomputation"]["status"] == "failed", r.text
    assert (await u.post(f"/v1/experiment-runs/{run_id}/promote")).json()["error"]["code"] == "not_recomputed"
    assert (await visible_run(u, p["id"], run_id))["recomputation"]["status"] == "failed"


async def test_passing_report_after_terminal_failure_cannot_rescue_the_run(client):
    """A validator report that arrives after a terminal failure must not make the run promotable."""
    u = await make_user(client)
    p = await make_project(u)
    run_id, task_id, h = await seed_run(u, p["id"])

    r = await client.post(RUN_PATH.format(run_id=run_id) + "/status", headers=h, json={
        "status": "failed", "exit_code": 1, "duration_s": 2.0, "failure_reason": "process exited 1"})
    assert r.status_code == 200 and r.json()["status"] == "failed", r.text

    report = {"status": "passed", "validator": "rp-experiment-validator/0.1",
              "checks": [{"id": "recompute:accuracy", "passed": True,
                          "evidence": {"reported": 0.75, "recomputed": 0.75, "n": 8, "tolerance": 1e-9}}],
              "summary": "recomputed accuracy matches"}
    art = await commit_json_artifact(client, h, p["id"], task_id, "recomputation_report", report)
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/recomputation", headers=h,
                          json={"artifact_id": art, "report": report})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "failed" and r.json()["promotable"] is False

    r = await u.post(f"/v1/experiment-runs/{run_id}/promote")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "run_not_succeeded"

    run = await visible_run(u, p["id"], run_id)
    assert run["status"] == "failed" and run["failure_reason"] == "process exited 1"
    assert run["reported_metrics"] is None
    await assert_not_a_result(u, p["id"], run)
