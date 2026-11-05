"""The API keeps the sandbox execution block the workers post on compile runs and experiment runs, and returns it
unchanged to callers, for successful and failed executions alike."""

from __future__ import annotations

import uuid

import pytest
from conftest import make_project, make_task, make_user, service_token
from test_m9_experiment_promotion import RUN_PATH, commit_json_artifact, seed_run, visible_run

EXECUTION_KEYS = {"status", "exit_code", "timed_out", "duration_s", "image", "argv", "stdout", "stderr", "failure_reason",
                  "output_error", "streams_collected"}


def execution(status: str, **over) -> dict:
    base = {"status": status, "exit_code": 0, "timed_out": False, "duration_s": 2.5, "image": "python-sci@sha256:" + "b" * 64,
            "argv": ["python", "main.py", "--seed", "7"], "stdout": {"text": "acc 0.75\n", "total_bytes": 9, "truncated": False},
            "stderr": {"text": "", "total_bytes": 0, "truncated": False}, "failure_reason": None, "output_error": None,
            "streams_collected": True}
    base.update(over)
    assert set(base) == EXECUTION_KEYS
    return base


@pytest.mark.parametrize("status,exe", [
    ("succeeded", execution("succeeded")),
    ("failed", execution("failed", exit_code=1, failure_reason="the program exited with code 1",
                         stderr={"text": "Traceback\nValueError\n", "total_bytes": 9000, "truncated": True})),
    ("timed_out", execution("timed_out", exit_code=124, timed_out=True, duration_s=60.0, streams_collected=False,
                            failure_reason="the run exceeded its time limit of 60s",
                            stderr={"text": "[sandbox] timed out after 60s", "total_bytes": 29, "truncated": False})),
    ("failed", execution("failed", exit_code=0, output_error="sandbox output exceeds the size limit", streams_collected=False,
                         failure_reason="the sandbox outputs could not be collected: sandbox output exceeds the size limit")),
])
async def test_experiment_run_keeps_the_execution_block(client, status, exe):
    u = await make_user(client)
    p = await make_project(u)
    run_id, _, h = await seed_run(u, p["id"])
    body = {"status": status, "exit_code": exe["exit_code"], "duration_s": exe["duration_s"],
            "failure_reason": exe["failure_reason"], "execution": exe}
    if status == "succeeded":
        body["reported_metrics"] = {"accuracy": 0.75}
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/status", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["execution"] == exe
    run = await visible_run(u, p["id"], run_id)
    assert run["execution"] == exe, "the researcher-facing run carries the identical block"
    assert (run["exit_code"], run["duration_s"], run["failure_reason"]) == (exe["exit_code"], exe["duration_s"], exe["failure_reason"])
    assert run["status"] == status


async def test_experiment_run_without_execution_block_stays_readable(client):
    u = await make_user(client)
    p = await make_project(u)
    run_id, _, h = await seed_run(u, p["id"])
    r = await client.post(RUN_PATH.format(run_id=run_id) + "/status", headers=h,
                          json={"status": "failed", "exit_code": 1, "failure_reason": "legacy worker"})
    assert r.status_code == 200 and r.json()["execution"] is None


async def seed_template(u, project_id: str) -> str:
    from rp_api.db.engine import session_scope
    from rp_api.db.models.latex import Template

    tid = uuid.uuid4()
    async with session_scope("system") as db:
        db.add(Template(id=tid, tenant_id=uuid.UUID(u.tenant_id), project_id=uuid.UUID(project_id), mode="submission",
                        origin="official_link", family="acmart", status="validated", supported=True))
        await db.commit()
    return str(tid)


@pytest.mark.parametrize("status,exe,checks", [
    ("compiled", execution("compiled", image="rp-latex-sandbox:1", argv=["docker", "run", "rp-latex-sandbox:1", "sh", "-c", "<fixed script>"],
                           stdout={"text": "Latexmk: All targets up-to-date\n", "total_bytes": 32, "truncated": False}),
     [{"id": "compile.success", "status": "passed", "detail": "PDF produced"}]),
    ("failed", execution("failed", image="rp-latex-sandbox:1", exit_code=12, argv=["docker", "run"],
                         failure_reason="compilation failed: ! Emergency stop.",
                         stderr={"text": "! Emergency stop.\n", "total_bytes": 7000, "truncated": True}),
     [{"id": "compile.success", "status": "failed", "detail": "compilation failed"}]),
    ("sandbox_unavailable", execution("sandbox_unavailable", exit_code=None, duration_s=None, image=None, argv=[],
                                      stdout={"text": "", "total_bytes": 0, "truncated": False},
                                      streams_collected=False, failure_reason="container runtime is not available"),
     [{"id": "compile.success", "status": "not_performed", "detail": "container runtime is not available"}]),
])
async def test_compile_run_keeps_the_execution_block(client, status, exe, checks):
    u = await make_user(client)
    p = await make_project(u)
    template_id = await seed_template(u, p["id"])
    task_id = await make_task(u.tenant_id, p["id"], kind="template_compile", params={"template_id": template_id})
    h = await service_token(client, task_id)
    report = {"status": status, "family": "acmart", "checks": checks, "errors": [], "execution": exe}
    report_id = await commit_json_artifact(client, h, p["id"], task_id, "compile_report", report)

    r = await client.post(f"/v1/internal/projects/{p['id']}/compile-runs", headers=h, json={
        "template_id": template_id, "kind": "sample", "options": {"mode": "submission"}, "status": status,
        "report_artifact_id": report_id, "checks": checks, "pages": 3 if status == "compiled" else None,
        "errors": [] if status == "compiled" else [exe["failure_reason"]], "execution": exe})
    assert r.status_code == 201, r.text
    assert r.json()["execution"] == exe and r.json()["status"] == status

    listing = await u.get(f"/v1/projects/{p['id']}/templates")
    assert listing.status_code == 200, listing.text
    tpl = next(t for t in listing.json()["items"] if t["id"] == template_id)
    run = next(cr for cr in tpl["compile_runs"] if cr["report_artifact_id"] == report_id)
    assert run["execution"] == exe, "the researcher-facing compile run carries the identical block"
    assert run["status"] == status and run["checks"] == checks


async def test_compile_run_without_execution_block_stays_readable(client):
    u = await make_user(client)
    p = await make_project(u)
    template_id = await seed_template(u, p["id"])
    task_id = await make_task(u.tenant_id, p["id"], kind="template_compile", params={})
    h = await service_token(client, task_id)
    report_id = await commit_json_artifact(client, h, p["id"], task_id, "compile_report", {"status": "compiled"})
    r = await client.post(f"/v1/internal/projects/{p['id']}/compile-runs", headers=h, json={
        "template_id": template_id, "kind": "sample", "options": {}, "status": "compiled", "report_artifact_id": report_id,
        "checks": []})
    assert r.status_code == 201, r.text
    assert r.json()["execution"] is None
