"""Agent/workflow event envelope (PRODUCT_SPEC §6). Consumers deduplicate on event_id."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import ActorType

EVENT_SCHEMA_VERSION = 1


class EventType(StrEnum):
    PROJECT_CREATED = "project.created"
    STATE_CHANGED = "state.changed"
    TASK_REQUESTED = "task.requested"
    TASK_UPDATED = "task.updated"
    TASK_FAILED = "task.failed"
    TASK_CANCEL_REQUESTED = "task.cancel_requested"
    ARTIFACT_COMMITTED = "artifact.committed"
    ARTIFACT_INVALIDATED = "artifact.invalidated"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_RECORDED = "approval.recorded"
    APPROVAL_INVALIDATED = "approval.invalidated"
    RULE_CHANGED = "rule.changed"
    BUDGET_THRESHOLD = "budget.threshold"
    PACKAGE_READY = "package.ready"
    PROJECT_CONTROL = "project.control"  # pause / resume / cancel signals for running work


class EventEnvelope(BaseModel):
    event_id: UUID
    schema_version: int = EVENT_SCHEMA_VERSION
    tenant_id: UUID
    project_id: UUID | None = None
    workflow_id: str | None = None
    task_id: UUID | None = None
    type: EventType
    occurred_at: datetime
    actor_type: ActorType
    actor_id: str
    input_manifest_hash: str | None = None
    output_artifact_ids: list[UUID] = Field(default_factory=list)
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
