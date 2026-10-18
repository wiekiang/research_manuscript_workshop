"""Fast-forward after a reopened gate is satisfied again.

Dependency invalidation reopens only the gate that consumed a changed artifact. Once that gate is satisfied,
the project moves forward again through every later gate whose approvals and evidence are still current, up to
the furthest state it had reached. Each step is an ordinary gated transition.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import ProjectState
from rp_contracts.state_machine import FORWARD_RULES, OVERLAYS, STATE_INDEX

from ..db.models.core import Project, ProjectEvent
from ..security.tokens import Principal
from . import gates as gate_registry
from .transitions import TransitionRequest, request_transition


async def high_water_mark(db: AsyncSession, project_id) -> ProjectState:
    states = (await db.execute(select(ProjectEvent.to_state).where(
        ProjectEvent.project_id == project_id, ProjectEvent.event_type == "state.changed"))).scalars().all()
    reached = [ProjectState(s) for s in states if s and ProjectState(s) not in OVERLAYS]
    return max(reached, key=lambda s: STATE_INDEX[s]) if reached else ProjectState.CREATED


async def fast_forward(db: AsyncSession, actor: Principal, project: Project) -> list[dict]:
    if project.state in {s.value for s in OVERLAYS}:
        return []
    target = await high_water_mark(db, project.id)
    steps = []
    while STATE_INDEX[ProjectState(project.state)] < STATE_INDEX[target]:
        rule = next((r for r in FORWARD_RULES if r.source.value == project.state), None)
        if rule is None:
            break
        results = await gate_registry.evaluate_all(db, project, rule.gates)
        if not all(r.passed for r in results):
            break
        res = await request_transition(db, actor, project.id, TransitionRequest(
            requested_state=rule.target, expected_project_version=project.version,
            idempotency_key=f"ff:{project.id}:{project.version}", cause="request",
            reason="gate satisfied again; later gates still current"))
        steps.append(res.as_dict())
    return steps
