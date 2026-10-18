"""Gate evaluator registry.

Every gate ID in rp_contracts.state_machine must have an evaluator. Gates owned by milestones that are not
implemented yet fail closed with an explicit reason. Milestone modules register evaluators at import time.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.state_machine import FORWARD_RULES

from ..db.models.core import Project


@dataclass
class GateResult:
    gate_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    next_action: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"gate_id": self.gate_id, "passed": self.passed, "reasons": self.reasons, "evidence": self.evidence,
                "next_action": self.next_action}


Evaluator = Callable[[AsyncSession, Project], Awaitable[GateResult]]
_REGISTRY: dict[str, Evaluator] = {}


def gate(gate_id: str):
    def deco(fn: Evaluator) -> Evaluator:
        _REGISTRY[gate_id] = fn
        return fn

    return deco


ALL_GATE_IDS = sorted({g for r in FORWARD_RULES for g in r.gates})


async def evaluate(db: AsyncSession, project: Project, gate_id: str) -> GateResult:
    fn = _REGISTRY.get(gate_id)
    if fn is None:
        return GateResult(gate_id, False, [f"gate {gate_id} has no evaluator in this release (fail closed)"])
    return await fn(db, project)


async def evaluate_all(db: AsyncSession, project: Project, gate_ids: tuple[str, ...] | list[str]) -> list[GateResult]:
    return [await evaluate(db, project, g) for g in gate_ids]


def registered() -> dict[str, Evaluator]:
    return dict(_REGISTRY)
