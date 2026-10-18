"""M0 foundation tables: identity, tenancy, projects, events, tasks, artifacts, approvals, ledger, ops, cost."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, GlobalMixin, IdMixin, TenantMixin, TimestampMixin, utcnow

UUIDArray = ARRAY(PG_UUID(as_uuid=True))


# --------------------------------------------------------------------------- identity / tenancy
class Tenant(Base, IdMixin, TimestampMixin):
    __tablename__ = "tenants"
    __scope__ = "identity"
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    __scope__ = "identity"
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(Text)
    external_subject: Mapped[str | None] = mapped_column(String(500), unique=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="active")
    responsibility_ack_at: Mapped[datetime | None] = mapped_column()
    responsibility_ack_version: Mapped[str | None] = mapped_column(String(40))
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column()
    last_login_at: Mapped[datetime | None] = mapped_column()


class Membership(Base, IdMixin, TimestampMixin):
    __tablename__ = "memberships"
    __scope__ = "membership"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)


class AuthSession(Base, IdMixin, TimestampMixin):
    __tablename__ = "auth_sessions"
    __scope__ = "identity_private"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column()
    rotated_to: Mapped[uuid.UUID | None] = mapped_column()
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip: Mapped[str | None] = mapped_column(String(64))


class SecretRecord(Base, IdMixin, TimestampMixin):
    """Envelope-encrypted secret material. Only the secrets service (system role) can read this table."""

    __tablename__ = "secret_records"
    __scope__ = "identity_private"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    purpose: Mapped[str] = mapped_column(String(80))
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    nonce: Mapped[bytes] = mapped_column()
    ciphertext: Mapped[bytes] = mapped_column()
    destroyed_at: Mapped[datetime | None] = mapped_column()


# --------------------------------------------------------------------------- projects / workflow
class Project(Base, TenantMixin):
    __tablename__ = "projects"
    title: Mapped[str] = mapped_column(String(300))
    topic: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(40), default="CREATED", index=True)
    resume_state: Mapped[str | None] = mapped_column(String(40))
    overlay_reason: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    target_mode: Mapped[str | None] = mapped_column(String(20))  # official | exploratory
    target_track_id: Mapped[uuid.UUID | None] = mapped_column()
    target_edition_id: Mapped[uuid.UUID | None] = mapped_column()
    method_instance_id: Mapped[uuid.UUID | None] = mapped_column()
    budget_cap_cents: Mapped[int] = mapped_column(Integer)
    stage_budget_limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    readiness_stage: Mapped[str] = mapped_column(String(40), default="research_proposal")
    model_provider: Mapped[str | None] = mapped_column(String(40))  # owner's choice: claude_cli | anthropic | fixture
    responsibility_notice_shown_at: Mapped[datetime | None] = mapped_column()
    deleted_at: Mapped[datetime | None] = mapped_column()


class ProjectMember(Base, TenantMixin):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    is_corresponding_author: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[uuid.UUID | None] = mapped_column()
    removed_at: Mapped[datetime | None] = mapped_column()


class ProjectEvent(Base, IdMixin):
    """Append-only transition/event history (UPDATE/DELETE blocked by trigger)."""

    __tablename__ = "project_events"
    __scope__ = "tenant_append_only"
    __table_args__ = (
        UniqueConstraint("project_id", "seq"),
        Index("uq_project_events_idem", "project_id", "idempotency_key", unique=True,
              postgresql_where="idempotency_key IS NOT NULL"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    seq: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(60))
    from_state: Mapped[str | None] = mapped_column(String(40))
    to_state: Mapped[str | None] = mapped_column(String(40))
    resulting_version: Mapped[int | None] = mapped_column(Integer)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    input_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    output_artifact_ids: Mapped[list[uuid.UUID]] = mapped_column(UUIDArray, default=list)
    validator_result_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    human_approval_id: Mapped[uuid.UUID | None] = mapped_column()
    method_definition_version: Mapped[str | None] = mapped_column(String(80))
    gate_results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class WorkflowTask(Base, TenantMixin):
    __tablename__ = "workflow_tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_manifest_hash: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_artifact_ids: Mapped[list[uuid.UUID]] = mapped_column(UUIDArray, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    compensation: Mapped[str | None] = mapped_column(String(200))
    temporal_workflow_id: Mapped[str | None] = mapped_column(String(200))
    waiting_reason: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(200))
    owner_label: Mapped[str] = mapped_column(String(80), default="platform")
    estimated_cost_cents: Mapped[int | None] = mapped_column(Integer)
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()


# --------------------------------------------------------------------------- artifacts
class ArtifactReservation(Base, TenantMixin):
    __tablename__ = "artifact_reservations"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_manifest_hash: Mapped[str] = mapped_column(String(64))
    output_kind: Mapped[str] = mapped_column(String(60))
    media_type: Mapped[str] = mapped_column(String(120))
    expected_hash: Mapped[str | None] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(20))
    label: Mapped[str | None] = mapped_column(String(300))
    temp_object_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), index=True)
    uploaded_hash: Mapped[str | None] = mapped_column(String(64))
    uploaded_size: Mapped[int | None] = mapped_column(BigInteger)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_id: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column()
    conflict_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Artifact(Base, TenantMixin):
    """Immutable artifact metadata. Content columns are protected by a trigger."""

    __tablename__ = "artifacts"
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(120))
    object_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30))
    freshness: Mapped[str] = mapped_column(String(10), default="current", index=True)
    classification: Mapped[str] = mapped_column(String(20))
    label: Mapped[str | None] = mapped_column(String(300))
    rights: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(unique=True)
    input_manifest_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(200))
    committed_at: Mapped[datetime | None] = mapped_column()
    available_at: Mapped[datetime | None] = mapped_column()
    stale_at: Mapped[datetime | None] = mapped_column()
    stale_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column()


class ArtifactDependency(Base, TenantMixin):
    __tablename__ = "artifact_dependencies"
    __table_args__ = (UniqueConstraint("parent_artifact_id", "child_artifact_id", "dependency_kind"),)
    parent_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    child_artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    dependency_kind: Mapped[str] = mapped_column(String(60))
    validator_version: Mapped[str | None] = mapped_column(String(80))


# --------------------------------------------------------------------------- approvals / decisions / ledger
class Approval(Base, TenantMixin):
    __tablename__ = "approvals"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    gate: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(20), default="valid", index=True)
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approver_role: Mapped[str] = mapped_column(String(20))
    declaration_text: Mapped[str] = mapped_column(Text)
    declaration_version: Mapped[str] = mapped_column(String(40))
    rationale: Mapped[str | None] = mapped_column(Text)
    content_manifest_hash: Mapped[str] = mapped_column(String(64))
    bound_artifacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    project_version: Mapped[int] = mapped_column(Integer)
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)
    invalidated_at: Mapped[datetime | None] = mapped_column()
    invalidation_reason: Mapped[str | None] = mapped_column(Text)
    invalidated_by_event: Mapped[uuid.UUID | None] = mapped_column()
    superseded_by: Mapped[uuid.UUID | None] = mapped_column()


class ApprovalDependency(Base, TenantMixin):
    __tablename__ = "approval_dependencies"
    __table_args__ = (UniqueConstraint("approval_id", "artifact_id"),)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"), index=True)
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    artifact_hash: Mapped[str] = mapped_column(String(64))


class HumanDecision(Base, TenantMixin):
    __tablename__ = "human_decisions"
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    decision_type: Mapped[str] = mapped_column(String(80))
    subject_type: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[str] = mapped_column(String(200))
    choice: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str | None] = mapped_column(Text)
    bound_artifact_hash: Mapped[str | None] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)


class ContributionLedgerEntry(Base, TenantMixin):
    __tablename__ = "contribution_ledger_entries"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    diff: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    source_action: Mapped[str] = mapped_column(String(120))
    source_ref: Mapped[str | None] = mapped_column(String(200))
    auto_captured: Mapped[bool] = mapped_column(Boolean, default=True)
    rationale: Mapped[str | None] = mapped_column(Text)
    rationale_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="recorded")  # recorded | corrected | verified | disputed
    correction_of: Mapped[uuid.UUID | None] = mapped_column()
    verified_by: Mapped[uuid.UUID | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column()


# --------------------------------------------------------------------------- ops: outbox, inbox, idempotency, audit, notifications
class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __scope__ = "outbox"
    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(60))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    available_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    dispatched_at: Mapped[datetime | None] = mapped_column(index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    dead_lettered_at: Mapped[datetime | None] = mapped_column()


class InboxRecord(Base, IdMixin):
    __tablename__ = "inbox_records"
    __table_args__ = (UniqueConstraint("consumer", "event_id"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    consumer: Mapped[str] = mapped_column(String(80))
    event_id: Mapped[uuid.UUID] = mapped_column()
    processed_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class IdempotencyRecord(Base, IdMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("tenant_id", "scope", "key"),)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    scope: Mapped[str] = mapped_column(String(300))
    key: Mapped[str] = mapped_column(String(200))
    actor_id: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class AuditLog(Base, IdMixin):
    """Append-only audit trail. tenant_id may be NULL only for identity events (login, registration)."""

    __tablename__ = "audit_log"
    __scope__ = "audit"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(80))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now(), index=True)


class Notification(Base, TenantMixin):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"))
    type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column()
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)


# --------------------------------------------------------------------------- cost / model gateway
class ModelInvocation(Base, TenantMixin):
    __tablename__ = "model_invocations"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    agent: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(40))  # generation | embedding | review
    provider: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(80))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_artifact_ids: Mapped[list[uuid.UUID]] = mapped_column(UUIDArray, default=list)
    output_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    data_classification: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))  # authorized | succeeded | failed | denied
    denial_reason: Mapped[str | None] = mapped_column(Text)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    actual_cost_cents: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[datetime | None] = mapped_column()


class UsageLedgerEntry(Base, TenantMixin):
    __tablename__ = "usage_ledger"
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    category: Mapped[str] = mapped_column(String(40))  # llm | embeddings | scholarly_api | compute | storage | egress | tex_compile
    stage: Mapped[str | None] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(60))
    units: Mapped[float] = mapped_column(Numeric(18, 6))
    unit: Mapped[str] = mapped_column(String(30))
    unit_price_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    actual_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    billing_source: Mapped[str] = mapped_column(String(30), default="platform")  # platform | researcher_connection
    connection_id: Mapped[uuid.UUID | None] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    model_invocation_id: Mapped[uuid.UUID | None] = mapped_column()
    non_cancellable: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(default=utcnow)


class BudgetAlert(Base, TenantMixin):
    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("project_id", "threshold_pct", "cap_cents"),)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    threshold_pct: Mapped[int] = mapped_column(Integer)
    cap_cents: Mapped[int] = mapped_column(Integer)
    spent_cents: Mapped[int] = mapped_column(Integer)


class BudgetChange(Base, TenantMixin):
    """Explicit human decisions to raise/lower a project cost ceiling (never automatic)."""

    __tablename__ = "budget_changes"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    previous_cap_cents: Mapped[int] = mapped_column(Integer)
    new_cap_cents: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    rationale: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- provider registry / data flow
class ProviderDefinition(Base, GlobalMixin):
    __tablename__ = "provider_definitions"
    __scope__ = "global"
    key: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))  # scholarly | model | fetch | submission
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_status: Mapped[str] = mapped_column(String(20), default="pending")  # cleared | pending | blocked
    gate_notes: Mapped[str | None] = mapped_column(Text)
    docs_url: Mapped[str | None] = mapped_column(String(500))
    terms_url: Mapped[str | None] = mapped_column(String(500))
    terms_reviewed_at: Mapped[datetime | None] = mapped_column()
    terms_reviewed_by: Mapped[str | None] = mapped_column(String(200))
    allowed_uses: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    retention: Mapped[str | None] = mapped_column(Text)
    caching_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    fulltext_rights: Mapped[str | None] = mapped_column(Text)
    rate_limit: Mapped[str | None] = mapped_column(String(200))
    allowed_classifications: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    requires_user_connection: Mapped[bool] = mapped_column(Boolean, default=False)
    contract_evidence: Mapped[str | None] = mapped_column(Text)


class DataFlowAttestation(Base, TenantMixin):
    __tablename__ = "data_flow_attestations"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    provider_key: Mapped[str] = mapped_column(String(60))
    data_kinds: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    max_classification: Mapped[str] = mapped_column(String(20))
    provider_retention_note: Mapped[str | None] = mapped_column(Text)
    attestation_text: Mapped[str] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column()
