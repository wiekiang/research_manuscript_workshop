"""Canonical transition service, approval engine, dependency invalidation and contribution ledger."""

from __future__ import annotations

import uuid

import pytest
from conftest import make_project, make_task, make_user, service_token

from rp_contracts.enums import Gate, LedgerCategory, ProjectState
from rp_contracts.state_machine import check_transition


@pytest.fixture
def open_gates(monkeypatch):
    """Make named gates pass for structural tests (real evaluators are tested per milestone)."""
    from rp_api.services import gates

    def _open(*ids):
        for gid in ids:
            async def ok(db, project, gid=gid):
                return gates.GateResult(gid, True)
            monkeypatch.setitem(gates._REGISTRY, gid, ok)
    return _open


def test_structural_rules():
    S = ProjectState
    assert check_transition(S.CREATED, S.TARGET_REVIEW).allowed
    assert not check_transition(S.CREATED, S.DRAFTING).allowed, "cannot skip stages"
    assert check_transition(S.DRAFTING, S.PAUSED).kind == "overlay"
    assert check_transition(S.PAUSED, S.DRAFTING, S.DRAFTING).kind == "resume"
    assert not check_transition(S.PAUSED, S.FINAL_APPROVAL, S.DRAFTING).allowed
    assert not check_transition(S.CANCELLED, S.CREATED).allowed
    assert check_transition(S.FINAL_APPROVAL, S.DRAFTING).kind == "reopen"


async def test_gate_fails_closed_without_evaluator(client):
    u = await make_user(client)
    p = await make_project(u)
    r = await u.post(f"/v1/projects/{p['id']}/advance", json={"requested_state": "TARGET_REVIEW", "expected_version": 1})
    assert r.status_code == 422 and r.json()["error"]["code"] == "gate_unsatisfied"
    detail = r.json()["error"]["details"]["gates"][0]
    assert detail["gate_id"] == "target.selected" and not detail["passed"]
    got = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert got["state"] == "CREATED" and got["next_step"]["target_state"] == "TARGET_REVIEW"


async def test_service_transition_stale_duplicate_and_skip(client, open_gates):
    open_gates("target.selected")
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    req = {"requested_state": "TARGET_REVIEW", "expected_project_version": 1, "idempotency_key": "wf-step-000001"}
    r1 = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json=req)
    assert r1.status_code == 200 and r1.json()["state"] == "TARGET_REVIEW" and r1.json()["version"] == 2
    # Duplicate delivery (e.g. Temporal activity retry) replays the result, never applies twice.
    r2 = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json=req)
    assert r2.status_code == 200 and r2.json()["replayed"] is True and r2.json()["version"] == 2
    # Same key, different body is a conflict.
    r3 = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h,
                           json={**req, "requested_state": "DIRECTION_REVIEW"})
    assert r3.status_code == 409
    # Stale expected version cannot overwrite canonical state.
    r4 = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json={
        "requested_state": "DIRECTION_REVIEW", "expected_project_version": 1, "idempotency_key": "wf-step-000002"})
    assert r4.status_code == 409 and r4.json()["error"]["code"] == "stale_version"
    # Skipping a stage is structurally impossible.
    r5 = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json={
        "requested_state": "DRAFTING", "expected_project_version": 2, "idempotency_key": "wf-step-000003"})
    assert r5.status_code == 409 and r5.json()["error"]["code"] == "transition_not_allowed"
    events = (await u.get(f"/v1/projects/{p['id']}/events")).json()["items"]
    assert [e["type"] for e in events].count("state.changed") == 1


async def test_human_gate_cannot_be_passed_by_a_service(client, open_gates):
    """H1 has a real evaluator: without a human approval a service transition is refused."""
    open_gates("target.selected", "cfp.confirmed")
    u = await make_user(client)
    p = await make_project(u)
    task = await make_task(u.tenant_id, p["id"])
    h = await service_token(client, task)
    for i, state in enumerate(["TARGET_REVIEW", "DIRECTION_REVIEW"], start=1):
        r = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json={
            "requested_state": state, "expected_project_version": i, "idempotency_key": f"advance-{i}-xxxx"})
        assert r.status_code == 200, r.text
    r = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json={
        "requested_state": "PROTOCOL_REVIEW", "expected_project_version": 3, "idempotency_key": "advance-3-xxxx",
        "human_approval_id": str(uuid.uuid4())})
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_not_valid"
    r = await client.post(f"/v1/internal/projects/{p['id']}/transitions", headers=h, json={
        "requested_state": "PROTOCOL_REVIEW", "expected_project_version": 3, "idempotency_key": "advance-4-xxxx"})
    assert r.status_code == 422
    assert any(g["gate_id"] == "h1.approved" and not g["passed"] for g in r.json()["error"]["details"]["gates"])


async def test_pause_resume_cancel(client):
    u = await make_user(client)
    p = await make_project(u)
    r = await u.post(f"/v1/projects/{p['id']}/pause", json={"expected_version": 1, "reason": "waiting for data"})
    assert r.status_code == 200 and r.json()["state"] == "PAUSED"
    got = (await u.get(f"/v1/projects/{p['id']}")).json()
    assert got["resume_state"] == "CREATED" and "waiting for data" in got["next_step"]["message"]
    r = await u.post(f"/v1/projects/{p['id']}/resume", json={"expected_version": 2})
    assert r.json()["state"] == "CREATED"
    r = await u.post(f"/v1/projects/{p['id']}/cancel", json={"expected_version": 3})
    assert r.json()["state"] == "CANCELLED"
    r = await u.post(f"/v1/projects/{p['id']}/resume", json={"expected_version": 4})
    assert r.status_code == 409


async def test_only_owner_controls_project(client):
    owner = await make_user(client)
    p = await make_project(owner)
    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import Membership

    reviewer = await make_user(client, workspace=None)
    async with session_scope("system") as db:
        db.add(Membership(tenant_id=uuid.UUID(owner.tenant_id), user_id=uuid.UUID(reviewer.user_id), role="member"))
        await db.commit()
    from rp_api.services.identity import login

    issued = await login(reviewer.email, reviewer.password, None, None, None)
    reviewer.token = issued.access_token
    # Not a project member yet -> invisible.
    assert (await reviewer.get(f"/v1/projects/{p['id']}")).status_code == 404
    r = await owner.post(f"/v1/projects/{p['id']}/members", json={"email": reviewer.email, "role": "reviewer"})
    assert r.status_code == 201
    assert (await reviewer.get(f"/v1/projects/{p['id']}")).status_code == 200
    r = await reviewer.post(f"/v1/projects/{p['id']}/pause", json={"expected_version": 1})
    assert r.status_code == 403
    r = await reviewer.post(f"/v1/projects/{p['id']}/contribution-ledger",
                            json={"category": "idea", "summary": "reviewer cannot add contributions"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- approval engine + invalidation
async def _ctx(u, project_id):
    from rp_api.security.tokens import Principal

    principal = Principal(kind="user", subject=u.user_id, user_id=uuid.UUID(u.user_id), tenant_id=uuid.UUID(u.tenant_id))
    return principal


async def test_approval_binding_invalidation_and_reopen(client, open_gates):
    from sqlalchemy import select

    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import Approval, Project
    from rp_api.errors import ApiError
    from rp_api.services import approvals, artifacts, invalidation
    from rp_api.services.approvals import DECLARATIONS
    from rp_api.services.transitions import TransitionRequest, request_transition

    open_gates("target.selected", "cfp.confirmed")
    u = await make_user(client)
    p = await make_project(u)
    actor = await _ctx(u, p["id"])
    pid = uuid.UUID(p["id"])
    async with session_scope("app", tenant_id=actor.tenant_id, user_id=actor.user_id) as db:
        project = (await db.execute(select(Project).where(Project.id == pid))).scalar_one()
        # M5 requires a selected method workflow before H1 can satisfy its gate.
        from rp_api.db.models.contribution import MethodWorkflowInstance

        db.add(MethodWorkflowInstance(tenant_id=actor.tenant_id, project_id=pid, definition_key="theoretical@1",
                                      study_type="theoretical", definition_version=1, venue_category="full_paper",
                                      enabled_for_submission_ready=True, track_accepts="unknown", selected_by=actor.user_id))
        await db.flush()
        direction = (await artifacts.publish_json(db, actor, actor.tenant_id, pid, "research_direction",
                                                  {"question": "Does X improve Y?"})).artifact
        unrelated = (await artifacts.publish_json(db, actor, actor.tenant_id, pid, "generic_json",
                                                  {"note": "deadline schedule"})).artifact
        derived = (await artifacts.publish_json(db, actor, actor.tenant_id, pid, "generic_json", {"plan": "uses direction"},
                                                depends_on=[direction.id])).artifact
        with pytest.raises(ApiError) as exc:
            await approvals.record_approval(db, actor, project, Gate.H1, [direction], declaration_accepted=True,
                                            declaration_text="I agree")
        assert exc.value.code == "declaration_required"
        h1 = await approvals.record_approval(db, actor, project, Gate.H1, [direction], declaration_accepted=True,
                                             declaration_text=DECLARATIONS[Gate.H1].text, rationale="my reasoning")
        for state in (ProjectState.TARGET_REVIEW, ProjectState.DIRECTION_REVIEW, ProjectState.PROTOCOL_REVIEW):
            await request_transition(db, actor, pid, TransitionRequest(
                requested_state=state, expected_project_version=project.version, idempotency_key=f"t-{state}",
                human_approval_id=h1.id if state == ProjectState.PROTOCOL_REVIEW else None))
        await db.commit()
        assert project.state == "PROTOCOL_REVIEW"

        # Changing something unrelated leaves H1 intact.
        res = await invalidation.invalidate(db, actor, project, [unrelated.id], "schedule updated", "inv-unrelated")
        assert res.invalidated_approvals == [] and project.state == "PROTOCOL_REVIEW"
        # Changing the direction marks dependents stale, invalidates H1 and reopens DIRECTION_REVIEW.
        res = await invalidation.invalidate(db, actor, project, [direction.id], "research question changed", "inv-dir")
        await db.commit()
        assert derived.id in res.stale_artifact_ids
        assert res.invalidated_approvals[0]["gate"] == "H1"
        assert project.state == "DIRECTION_REVIEW"
        appr = (await db.execute(select(Approval).where(Approval.id == h1.id))).scalar_one()
        assert appr.status == "invalidated"
        # A stale artifact cannot be approved again; the current version must be approved.
        await db.refresh(direction)
        with pytest.raises(ApiError) as exc:
            await approvals.record_approval(db, actor, project, Gate.H1, [direction], declaration_accepted=True,
                                            declaration_text=DECLARATIONS[Gate.H1].text)
        assert exc.value.code == "stale_artifact"


async def test_approval_rows_resist_tampering(client):
    from sqlalchemy import select, text
    from sqlalchemy.exc import DBAPIError

    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import Project
    from rp_api.services import approvals, artifacts
    from rp_api.services.approvals import DECLARATIONS

    u = await make_user(client)
    p = await make_project(u)
    actor = await _ctx(u, p["id"])
    pid = uuid.UUID(p["id"])
    async with session_scope("app", tenant_id=actor.tenant_id, user_id=actor.user_id) as db:
        project = (await db.execute(select(Project).where(Project.id == pid))).scalar_one()
        art = (await artifacts.publish_json(db, actor, actor.tenant_id, pid, "research_direction", {"q": "tamper"})).artifact
        appr = await approvals.record_approval(db, actor, project, Gate.H1, [art], declaration_accepted=True,
                                               declaration_text=DECLARATIONS[Gate.H1].text)
        await db.commit()
        aid = appr.id
    for stmt in ("UPDATE approvals SET content_manifest_hash = repeat('0', 64) WHERE id = :i",
                 "DELETE FROM approvals WHERE id = :i"):
        async with session_scope("app", tenant_id=actor.tenant_id, user_id=actor.user_id) as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(stmt), {"i": aid})
    async with session_scope("app", tenant_id=actor.tenant_id, user_id=actor.user_id) as db:
        await db.execute(text("UPDATE approvals SET status = 'invalidated' WHERE id = :i"), {"i": aid})
        await db.commit()
    async with session_scope("app", tenant_id=actor.tenant_id, user_id=actor.user_id) as db:
        with pytest.raises(DBAPIError):
            await db.execute(text("UPDATE approvals SET status = 'valid' WHERE id = :i"), {"i": aid})


async def test_ledger_capture_correct_verify(client):
    from sqlalchemy import select

    from rp_api.db.engine import session_scope
    from rp_api.db.models.core import Project
    from rp_api.services import ledger

    u = await make_user(client)
    p = await make_project(u)
    actor = await _ctx(u, p["id"])
    async with session_scope("app", tenant_id=actor.tenant_id, user_id=actor.user_id) as db:
        project = (await db.execute(select(Project).where(Project.id == uuid.UUID(p["id"])))).scalar_one()
        diff = ledger.text_diff("Does X help?", "Does X improve Y under drift?", "research question")
        e = await ledger.capture(db, actor, project, LedgerCategory.QUESTION_REFINEMENT, "Refined the RQ",
                                 source_action="direction.edit", diff=diff)
        assert e is not None and e.rationale_requested is False
        svc = actor.__class__(kind="service", subject="service:x", service_name="x", tenant_id=actor.tenant_id)
        assert await ledger.capture(db, svc, project, LedgerCategory.IDEA, "agent idea", source_action="agent") is None
        await db.commit()
    r = await u.get(f"/v1/projects/{p['id']}/contribution-ledger")
    items = r.json()["items"]
    assert len(items) == 1 and "improve Y" in items[0]["diff"]
    r = await u.post(f"/v1/projects/{p['id']}/contribution-ledger/{items[0]['id']}/correct",
                     json={"summary": "Refined the RQ to target distribution drift", "rationale": "prior work gap"})
    assert r.status_code == 201
    r = await u.post(f"/v1/projects/{p['id']}/contribution-ledger/verify")
    assert r.json()["verified_entries"] == 1
    items = (await u.get(f"/v1/projects/{p['id']}/contribution-ledger")).json()["items"]
    assert {i["status"] for i in items} == {"corrected", "verified"}
