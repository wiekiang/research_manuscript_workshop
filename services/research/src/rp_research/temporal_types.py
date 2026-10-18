"""Serializable workflow inputs/outputs (dataclasses are Temporal-friendly)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskInput:
    task_id: str
    project_id: str | None
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    input_manifest_hash: str | None = None


@dataclass
class TaskOutcome:
    state: str  # succeeded | waiting_human | failed_terminal | cancelled
    output_artifact_ids: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    waiting_reason: str | None = None


@dataclass
class TransitionAsk:
    task_id: str
    project_id: str
    requested_state: str
    idempotency_key: str
    output_artifact_ids: list[str] = field(default_factory=list)
    input_manifest_hash: str | None = None
    validator_result_ids: list[str] = field(default_factory=list)
    only_from_states: list[str] = field(default_factory=list)


@dataclass
class TransitionAnswer:
    applied: bool
    state: str
    version: int
    reason: str = ""
