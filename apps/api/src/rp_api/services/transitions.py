"""The single writer of canonical project state (PRODUCT_SPEC §3 "Single transition owner").

`request_transition` runs inside the caller's transaction: it locks the project row, checks the expected
version, replays duplicate idempotency keys, validates the structural rule, confirms every output artifact
is committed, evaluates gates, then updates state/version and appends the event + outbox row atomically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import ProjectState
from rp_contracts.events import EventType
from rp_contracts.hashing import content_hash
from rp_contracts.state_machine import OVERLAYS, STATE_INDEX, check_transition

from ..db.models.core import Project, ProjectEvent
from ..errors import ApiError, conflict, not_found
from ..security.tokens import Principal
from . import gates as gate_registry
from .artifacts import require_committed
from .common import audit, emit


@dataclass
class TransitionRequest:
    requested_state: ProjectState
    expected_project_version: int
    idempotency_key: str
    input_manifest_hash: str | None = None
    output_artifact_ids: list[uuid.UUID] = field(default_factory=list)
    validator_result_ids: list[str] = field(default_factory=list)
    human_approval_id: uuid.UUID | None = None
    method_definition_version: str | None = None
    reason: str | None = None
    cause: str = "request"  # request | approval | invalidation | control | rerun


@dataclass
class TransitionResult:
    project_id: uuid.UUID
    from_state: str
    state: str
    version: int
    event_id: uuid.UUID
    replayed: bool
    gate_results: list[dict[str, Any]]
    invalidation_events: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id), "from_state": self.from_state, "state": self.state,
            "version": self.version, "event_id": str(self.event_id), "replayed": self.replayed,
            "gate_results": self.gate_results, "invalidation_events": self.invalidation_events,
        }


def _request_hash(req: TransitionRequest) -> str:
    return content_hash({
        "requested_state": req.requested_state.value,
        "expected_project_version": req.expected_project_version,
        "input_manifest_hash": req.input_manifest_hash,
        "output_artifact_ids": sorted(str(i) for i in req.output_artifact_ids),
        "validator_result_ids": sorted(req.validator_result_ids),
        "human_approval_id": str(req.human_approval_id) if req.human_approval_id else None,
        "method_definition_version": req.method_definition_version,
    })


async def next_seq(db: AsyncSession, project_id: uuid.UUID) -> int:
    cur = (await db.execute(select(func.max(ProjectEvent.seq)).where(ProjectEvent.project_id == project_id))).scalar()
    return (cur or 0) + 1


async def append_event(
    db: AsyncSession, project: Project, actor: Principal, event_type: str, *, from_state: str | None = None,
    to_state: str | None = None, payload: dict[str, Any] | None = None, idempotency_key: str | None = None,
    request_hash: str | None = None, input_manifest_hash: str | None = None,
    output_artifact_ids: list[uuid.UUID] | None = None, human_approval_id: uuid.UUID | None = None,
    gate_results: dict[str, Any] | None = None, method_definition_version: str | None = None,
    validator_result_ids: list[str] | None = None,
) -> ProjectEvent:
    ev = ProjectEvent(
        id=uuid.uuid4(), tenant_id=project.tenant_id, project_id=project.id, seq=await next_seq(db, project.id),
        event_type=event_type, from_state=from_state, to_state=to_state, resulting_version=project.version,
        actor_type=actor.actor_type, actor_id=actor.actor_id, idempotency_key=idempotency_key,
        request_hash=request_hash, input_manifest_hash=input_manifest_hash,
        output_artifact_ids=output_artifact_ids or [], validator_result_ids=validator_result_ids or [],
        human_approval_id=human_approval_id, method_definition_version=method_definition_version,
        gate_results=gate_results or {}, payload=payload or {},
    )
    db.add(ev)
    await db.flush()
    return ev


async def request_transition(
    db: AsyncSession, actor: Principal, project_id: uuid.UUID, req: TransitionRequest
) -> TransitionResult:
    project = (
        await db.execute(select(Project).where(Project.id == project_id).with_for_update())
    ).scalar_one_or_none()
    if project is None or project.deleted_at is not None:
        raise not_found("project")
    rhash = _request_hash(req)

    # Duplicate delivery: return the original outcome; never apply twice.
    prior = (
        await db.execute(
            select(ProjectEvent).where(
                ProjectEvent.project_id == project_id, ProjectEvent.idempotency_key == req.idempotency_key
            )
        )
    ).scalar_one_or_none()
    if prior is not None:
        if prior.request_hash != rhash:
            raise conflict("idempotency_conflict", "idempotency key reused with a different transition request")
        return TransitionResult(project.id, prior.from_state or "", prior.to_state or "", prior.resulting_version or 0,
                                prior.id, True, list((prior.gate_results or {}).get("results", [])))

    if project.version != req.expected_project_version:
        raise conflict("stale_version", "project version changed; reload state and retry",
                       {"expected": req.expected_project_version, "current": project.version, "state": project.state})

    current = ProjectState(project.state)
    resume = ProjectState(project.resume_state) if project.resume_state else None
    check = check_transition(current, req.requested_state, resume)
    if not check.allowed:
        raise conflict("transition_not_allowed", check.reason,
                       {"from": current.value, "to": req.requested_state.value})
    if check.kind == "reopen" and req.cause not in {"invalidation", "rerun"}:
        raise conflict("transition_not_allowed", "earlier gates reopen only through invalidation or an explicit rerun",
                       {"from": current.value, "to": req.requested_state.value})
    if actor.kind == "service" and check.kind in {"overlay", "resume"} and req.requested_state == ProjectState.CANCELLED:
        raise ApiError(403, "forbidden", "services cannot cancel projects")

    await require_committed(db, req.output_artifact_ids, project.id)

    results: list[gate_registry.GateResult] = []
    target_for_gates = req.requested_state if check.kind == "forward" else None
    if check.kind == "resume" and resume is not None:
        # Resuming re-validates nothing new, but a cancelled/blocked cause must be cleared by the caller.
        pass
    if target_for_gates is not None:
        results = await gate_registry.evaluate_all(db, project, check.gates)
        failed = [r for r in results if not r.passed]
        if failed:
            raise ApiError(422, "gate_unsatisfied", "one or more gates are not satisfied",
                           {"gates": [r.as_dict() for r in results]})

    from_state = project.state
    if check.kind == "overlay":
        if current not in OVERLAYS:
            project.resume_state = current.value
        project.overlay_reason = req.reason
    elif check.kind == "resume":
        project.resume_state = None
        project.overlay_reason = None
    project.state = req.requested_state.value
    project.version += 1
    gate_payload = {"results": [r.as_dict() for r in results]}
    ev = await append_event(
        db, project, actor, "state.changed", from_state=from_state, to_state=project.state,
        payload={"kind": check.kind, "cause": req.cause, "reason": req.reason},
        idempotency_key=req.idempotency_key, request_hash=rhash, input_manifest_hash=req.input_manifest_hash,
        output_artifact_ids=req.output_artifact_ids, human_approval_id=req.human_approval_id,
        gate_results=gate_payload, method_definition_version=req.method_definition_version,
        validator_result_ids=req.validator_result_ids,
    )
    emit(db, tenant_id=project.tenant_id, type=EventType.STATE_CHANGED, actor_type=actor.actor_type,
         actor_id=actor.actor_id, project_id=project.id, input_manifest_hash=req.input_manifest_hash,
         output_artifact_ids=req.output_artifact_ids,
         payload={"from": from_state, "to": project.state, "version": project.version, "kind": check.kind,
                  "cause": req.cause})
    await audit(db, actor, "project.transition", tenant_id=project.tenant_id, project_id=project.id,
                resource_type="project", resource_id=project.id,
                details={"from": from_state, "to": project.state, "cause": req.cause, "kind": check.kind})
    return TransitionResult(project.id, from_state, project.state, project.version, ev.id, False, gate_payload["results"])


async def reopen_to(db: AsyncSession, actor: Principal, project: Project, target: ProjectState, reason: str,
                    cause_key: str) -> TransitionResult | None:
    """Move a project back to the state owning an invalidated gate (dependency invalidation).

    If the project is under an overlay, the saved resume state is lowered instead.
    """
    if project.state in {s.value for s in OVERLAYS}:
        if project.resume_state and STATE_INDEX[ProjectState(project.resume_state)] > STATE_INDEX[target]:
            prev = project.resume_state
            project.resume_state = target.value
            project.version += 1
            await append_event(db, project, actor, "resume_state.lowered", from_state=prev, to_state=target.value,
                               payload={"reason": reason}, idempotency_key=cause_key)
        return None
    if STATE_INDEX[ProjectState(project.state)] <= STATE_INDEX[target]:
        return None
    return await request_transition(
        db, actor, project.id,
        TransitionRequest(requested_state=target, expected_project_version=project.version,
                          idempotency_key=cause_key, reason=reason, cause="invalidation"),
    )
