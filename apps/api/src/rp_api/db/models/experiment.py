"""M9 platform-executed experiment tables (tenant-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class ExperimentPlan(Base, TenantMixin):
    __tablename__ = "experiment_plans"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    method_instance_id: Mapped[uuid.UUID] = mapped_column()
    protocol_id: Mapped[uuid.UUID] = mapped_column()
    protocol_hash: Mapped[str] = mapped_column(String(64))
    plan_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    image_ref: Mapped[str] = mapped_column(Text)  # name@sha256 digest resolved from the allowlist
    code_hash: Mapped[str] = mapped_column(String(64))
    input_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    run_type: Mapped[str] = mapped_column(String(20))
    synthetic: Mapped[bool] = mapped_column(default=False)
    estimate_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | superseded
    artifact_id: Mapped[uuid.UUID] = mapped_column()
    approved_by: Mapped[uuid.UUID | None] = mapped_column()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_rationale: Mapped[str | None] = mapped_column(Text)


class ExperimentRun(Base, TenantMixin):
    __tablename__ = "experiment_runs"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("experiment_plans.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    rerun_of: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), default="queued")  # queued|running|succeeded|failed|timed_out|sandbox_unavailable|cancelled
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    run_manifest_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    raw_output_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    predictions_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    log_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    reported_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recomputation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    recomputation_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    reproduction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result_manifest_id: Mapped[uuid.UUID | None] = mapped_column()
    failure_reason: Mapped[str | None] = mapped_column(Text)
