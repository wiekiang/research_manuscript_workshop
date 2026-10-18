"""Audit log, outbox emission, idempotency records and notifications (shared by all services)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.events import EventEnvelope, EventType
from rp_contracts.hashing import content_hash

from ..db.base import utcnow
from ..db.models.core import AuditLog, IdempotencyRecord, Notification, OutboxEvent
from ..errors import unprocessable
from ..observability import request_id_var
from ..security.tokens import Principal


async def audit(
    db: AsyncSession,
    actor: Principal | None,
    action: str,
    *,
    tenant_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: Any = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id or (actor.tenant_id if actor else None),
            project_id=project_id,
            actor_type=actor.actor_type if actor else "system",
            actor_id=actor.actor_id if actor else "system",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            request_id=request_id_var.get(),
            ip=ip,
            details=details or {},
        )
    )


def emit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    type: EventType,
    actor_type: str,
    actor_id: str,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    workflow_id: str | None = None,
    input_manifest_hash: str | None = None,
    output_artifact_ids: list[uuid.UUID] | None = None,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> EventEnvelope:
    env = EventEnvelope(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        project_id=project_id,
        workflow_id=workflow_id,
        task_id=task_id,
        type=type,
        occurred_at=utcnow(),
        actor_type=actor_type,  # type: ignore[arg-type]
        actor_id=actor_id,
        input_manifest_hash=input_manifest_hash,
        output_artifact_ids=output_artifact_ids or [],
        correlation_id=correlation_id or request_id_var.get(),
        payload=payload or {},
    )
    db.add(
        OutboxEvent(
            event_id=env.event_id,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=type.value,
            envelope=env.model_dump(mode="json"),
        )
    )
    return env


async def idempotency_lookup(
    db: AsyncSession, tenant_id: uuid.UUID, scope: str, key: str | None, request_body: Any
) -> IdempotencyRecord | None:
    """Return a stored response for a replayed key; raise if the key was reused with a different body."""
    if not key:
        return None
    if len(key) > 200:
        raise unprocessable("invalid_idempotency_key", "Idempotency-Key must be at most 200 characters")
    rec = (
        await db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id, IdempotencyRecord.scope == scope, IdempotencyRecord.key == key
            )
        )
    ).scalar_one_or_none()
    if rec is not None and rec.request_hash != content_hash(request_body):
        raise unprocessable(
            "idempotency_key_reused", "this Idempotency-Key was already used with a different request body"
        )
    return rec


def idempotency_store(
    db: AsyncSession, tenant_id: uuid.UUID, scope: str, key: str | None, actor_id: str, request_body: Any,
    status_code: int, response: Any,
) -> None:
    if not key:
        return
    db.add(
        IdempotencyRecord(
            tenant_id=tenant_id, scope=scope, key=key, actor_id=actor_id, request_hash=content_hash(request_body),
            status_code=status_code, response=response,
        )
    )


def notify(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, type: str, title: str,
    project_id: uuid.UUID | None = None, body: str | None = None, link: str | None = None, dedupe_key: str | None = None,
) -> None:
    db.add(Notification(tenant_id=tenant_id, user_id=user_id, project_id=project_id, type=type, title=title,
                        body=body, link=link, dedupe_key=dedupe_key))
