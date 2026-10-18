"""M0.3 acceptance: transitions and artifact commits survive crash/retry without duplicate or orphaned evidence."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from conftest import drain_outbox, make_project, make_user
from temporalio.worker import Worker
from wf_testing import CRASHES, FlakyPublishWorkflow, SlowWorkflow, flaky_publish, slow_step

from rp_contracts.tasks import QUEUE_RESEARCH
from rp_research.registry import ACTIVITIES, WORKFLOWS
from rp_research.temporal_types import TaskInput

pytestmark = pytest.mark.temporal


def _worker(env):
    return Worker(env.client, task_queue=QUEUE_RESEARCH,
                  workflows=[*WORKFLOWS[QUEUE_RESEARCH], FlakyPublishWorkflow, SlowWorkflow],
                  activities=[*ACTIVITIES[QUEUE_RESEARCH], flaky_publish, slow_step])


async def _task(u, project_id: str, mode: str, advance: bool = False) -> tuple[str, TaskInput]:
    from rp_api.testing import make_task

    tid = await make_task(u.tenant_id, project_id, kind="cfp_import", params={"mode": mode, "advance": advance})
    return tid, TaskInput(task_id=tid, project_id=project_id, kind="cfp_import", params={"mode": mode, "advance": advance},
                          input_manifest_hash="9" * 64)


async def _artifacts(u, pid):
    return (await u.get(f"/v1/projects/{pid}/artifacts")).json()["items"]


@pytest.mark.parametrize("mode", ["before_commit", "after_commit"])
async def test_crash_and_retry_publishes_exactly_once(client, temporal_env, mode):
    u = await make_user(client)
    p = await make_project(u)
    tid, inp = await _task(u, p["id"], mode)
    async with _worker(temporal_env):
        out = await temporal_env.client.execute_workflow(FlakyPublishWorkflow.run, inp, id=f"task-{tid}",
                                                         task_queue=QUEUE_RESEARCH)
    assert out.state == "succeeded" and CRASHES[mode] == 2
    arts = await _artifacts(u, p["id"])
    assert len(arts) == 1 and arts[0]["id"] == out.output_artifact_ids[0]
    task = next(t for t in (await u.get(f"/v1/projects/{p['id']}/tasks")).json()["items"] if t["id"] == tid)
    assert task["state"] == "succeeded" and task["output_artifact_ids"] == out.output_artifact_ids


async def test_duplicate_transition_delivery_applies_once(client, temporal_env, monkeypatch):
    from rp_api.services import gates

    async def ok(db, project):
        return gates.GateResult("target.selected", True)

    monkeypatch.setitem(gates._REGISTRY, "target.selected", ok)
    u = await make_user(client)
    p = await make_project(u)
    tid, inp = await _task(u, p["id"], "plain", advance=True)
    async with _worker(temporal_env):
        await temporal_env.client.execute_workflow(FlakyPublishWorkflow.run, inp, id=f"task-{tid}",
                                                   task_queue=QUEUE_RESEARCH)
    proj = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert proj["state"] == "TARGET_REVIEW" and proj["version"] == 2
    events = (await u.get(f"/v1/projects/{p['id']}/events")).json()["items"]
    assert [e["type"] for e in events].count("state.changed") == 1


async def test_relay_starts_project_workflow_and_notifies_waiting_human(client, temporal_env, monkeypatch):
    from rp_api.services import gates

    async def ok(db, project):
        return gates.GateResult("target.selected", True)

    monkeypatch.setitem(gates._REGISTRY, "target.selected", ok)
    u = await make_user(client)
    p = await make_project(u)
    r = await u.post(f"/v1/projects/{p['id']}/advance", json={"requested_state": "TARGET_REVIEW", "expected_version": 1})
    assert r.status_code == 200
    async with _worker(temporal_env):
        await drain_outbox(temporal_env)
        await drain_outbox(temporal_env)  # duplicate dispatch attempts are harmless
        handle = temporal_env.client.get_workflow_handle(f"project-{p['id']}")
        for _ in range(100):
            notes = (await u.get("/v1/notifications")).json()["items"]
            if any(n["type"] == "approval.required" for n in notes):
                break
            await asyncio.sleep(0.1)
        status = await handle.query("status")
    assert status["state"] == "TARGET_REVIEW"
    notes = [n for n in (await u.get("/v1/notifications")).json()["items"] if n["type"] == "approval.required"]
    assert len(notes) == 1 and "Confirm the selected track" in notes[0]["title"]


async def test_cancel_stops_running_task_and_preserves_audit(client, temporal_env):
    u = await make_user(client)
    p = await make_project(u)
    from rp_api.testing import make_task

    tid = await make_task(u.tenant_id, p["id"], kind="cfp_import")
    inp = TaskInput(task_id=tid, project_id=p["id"], kind="cfp_import")
    async with _worker(temporal_env):
        handle = await temporal_env.client.start_workflow(SlowWorkflow.run, inp, id=f"task-{tid}",
                                                          task_queue=QUEUE_RESEARCH)
        for _ in range(100):
            t = next(t for t in (await u.get(f"/v1/projects/{p['id']}/tasks")).json()["items"] if t["id"] == tid)
            if t["state"] == "running":
                break
            await asyncio.sleep(0.05)
        r = await u.post(f"/v1/projects/{p['id']}/cancel", json={"expected_version": 1, "reason": "wrong venue"})
        assert r.status_code == 200
        await drain_outbox(temporal_env)
        with pytest.raises(Exception):
            await handle.result()
    t = next(t for t in (await u.get(f"/v1/projects/{p['id']}/tasks")).json()["items"] if t["id"] == tid)
    assert t["state"] == "cancelled"
    events = (await u.get(f"/v1/projects/{p['id']}/events")).json()["items"]
    assert events[-1]["to_state"] == "CANCELLED"


async def test_paused_project_holds_task_until_resumed(client, temporal_env):
    u = await make_user(client)
    p = await make_project(u)
    await u.post(f"/v1/projects/{p['id']}/pause", json={"expected_version": 1, "reason": "budget review"})
    tid, inp = await _task(u, p["id"], "plain")
    async with _worker(temporal_env):
        handle = await temporal_env.client.start_workflow(FlakyPublishWorkflow.run, inp, id=f"task-{tid}",
                                                          task_queue=QUEUE_RESEARCH)
        await asyncio.sleep(1.0)
        assert await _artifacts(u, p["id"]) == [], "no work happens while paused"
        await u.post(f"/v1/projects/{p['id']}/resume", json={"expected_version": 2})
        out = await handle.result()
    assert out.state == "succeeded" and len(await _artifacts(u, p["id"])) == 1


async def test_reconcile_workflow_via_maintenance_token(client, temporal_env):
    async with _worker(temporal_env):
        report = await temporal_env.client.execute_workflow("ReconcileWorkflow", id=f"reconcile-{uuid.uuid4()}",
                                                            task_queue=QUEUE_RESEARCH)
    assert "deleted_orphans" in report
