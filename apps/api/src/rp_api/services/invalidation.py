"""Dependency-based invalidation (PRODUCT_SPEC §3).

Walks only reachable dependents of the changed artifacts, marks them stale, invalidates approvals that
consumed them, runs domain hooks (claims, spans, compliance reports ...) and reopens the earliest gate whose
approval was invalidated. Prior versions are never deleted.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import ApprovalStatus, Freshness, Gate, ProjectState
from rp_contracts.events import EventType
from rp_contracts.state_machine import STATE_INDEX

from ..db.base import utcnow
from ..db.models.core import Approval, ApprovalDependency, Artifact, ArtifactDependency, Project
from ..security.tokens import Principal
from .approvals import invalidate_approval
from .common import audit, emit
from .transitions import reopen_to

# Gate -> project state that owns it (where the project returns when the approval is invalidated)
GATE_HOME: dict[str, ProjectState] = {
    Gate.CFP.value: ProjectState.TARGET_REVIEW,
    Gate.H1.value: ProjectState.DIRECTION_REVIEW,
    Gate.H2.value: ProjectState.PROTOCOL_REVIEW,
    Gate.H3.value: ProjectState.OUTCOME_REVIEW,
    Gate.H4.value: ProjectState.FINAL_APPROVAL,
}

Hook = Callable[[AsyncSession, Principal, Project, set[uuid.UUID], str], Awaitable[list[str]]]
_HOOKS: list[Hook] = []


def on_stale(fn: Hook) -> Hook:
    """Register a domain hook called with the full stale artifact set. Returns human-readable effects."""
    _HOOKS.append(fn)
    return fn


@dataclass
class InvalidationResult:
    stale_artifact_ids: list[uuid.UUID] = field(default_factory=list)
    invalidated_approvals: list[dict[str, str]] = field(default_factory=list)
    effects: list[str] = field(default_factory=list)
    reopened_to: str | None = None

    def as_dict(self) -> dict:
        return {"stale_artifact_ids": [str(i) for i in self.stale_artifact_ids],
                "invalidated_approvals": self.invalidated_approvals, "effects": self.effects,
                "reopened_to": self.reopened_to}


async def descendants(db: AsyncSession, roots: set[uuid.UUID]) -> set[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    frontier = set(roots)
    while frontier:
        rows = (await db.execute(
            select(ArtifactDependency.child_artifact_id).where(ArtifactDependency.parent_artifact_id.in_(frontier))
        )).scalars().all()
        frontier = {r for r in rows if r not in seen and r not in roots}
        seen |= frontier
    return seen


async def invalidate(
    db: AsyncSession, actor: Principal, project: Project, changed: list[uuid.UUID], reason: str, cause_key: str,
    *, mark_roots_stale: bool = True,
) -> InvalidationResult:
    roots = set(changed)
    downstream = await descendants(db, roots)
    stale = (roots if mark_roots_stale else set()) | downstream
    result = InvalidationResult()
    if stale:
        arts = list((await db.execute(select(Artifact).where(Artifact.id.in_(stale)))).scalars())
        now = utcnow()
        for a in arts:
            if a.freshness != Freshness.STALE:
                a.freshness = Freshness.STALE
                a.stale_at = now
                a.stale_reason = reason
                result.stale_artifact_ids.append(a.id)
    # Approvals bound to anything stale (including roots even when roots are not marked stale: they changed).
    affected = stale | roots
    approval_ids = (await db.execute(
        select(ApprovalDependency.approval_id).where(ApprovalDependency.artifact_id.in_(affected))
    )).scalars().all()
    approvals = list((await db.execute(
        select(Approval).where(Approval.id.in_(set(approval_ids)), Approval.status == ApprovalStatus.VALID)
    )).scalars()) if approval_ids else []
    for appr in approvals:
        await invalidate_approval(db, actor, appr, reason)
        result.invalidated_approvals.append({"gate": appr.gate, "approval_id": str(appr.id)})
    for hook in _HOOKS:
        result.effects += await hook(db, actor, project, affected, reason)
    if result.stale_artifact_ids:
        emit(db, tenant_id=project.tenant_id, type=EventType.ARTIFACT_INVALIDATED, actor_type=actor.actor_type,
             actor_id=actor.actor_id, project_id=project.id, output_artifact_ids=result.stale_artifact_ids,
             payload={"reason": reason, "invalidated_gates": [a["gate"] for a in result.invalidated_approvals]})
    homes = [GATE_HOME[a["gate"]] for a in result.invalidated_approvals if a["gate"] in GATE_HOME]
    if homes:
        target = min(homes, key=lambda s: STATE_INDEX[s])
        tr = await reopen_to(db, actor, project, target, reason, f"{cause_key}:reopen")
        result.reopened_to = tr.state if tr else None
    await audit(db, actor, "dependency.invalidation", tenant_id=project.tenant_id, project_id=project.id,
                details={"reason": reason, **result.as_dict()})
    return result


async def link(db: AsyncSession, tenant_id: uuid.UUID, parent_id: uuid.UUID, child_id: uuid.UUID,
               kind: str = "derived_from", validator_version: str | None = None) -> None:
    exists = (await db.execute(select(ArtifactDependency).where(
        ArtifactDependency.parent_artifact_id == parent_id, ArtifactDependency.child_artifact_id == child_id,
        ArtifactDependency.dependency_kind == kind))).scalar_one_or_none()
    if exists is None:
        db.add(ArtifactDependency(tenant_id=tenant_id, parent_artifact_id=parent_id, child_artifact_id=child_id,
                                  dependency_kind=kind, validator_version=validator_version))
