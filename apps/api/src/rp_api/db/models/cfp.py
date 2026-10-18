"""M1/M2 CFP intelligence tables (tenant-owned)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TenantMixin


class Conference(Base, TenantMixin):
    __tablename__ = "conferences"
    __table_args__ = (UniqueConstraint("tenant_id", "series_key"),)
    name: Mapped[str] = mapped_column(String(400))
    acronym: Mapped[str | None] = mapped_column(String(40))
    series_key: Mapped[str] = mapped_column(String(200))
    organizer: Mapped[str | None] = mapped_column(String(300))
    official_url: Mapped[str | None] = mapped_column(String(2048))
    questionable_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    questionable_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)


class ConferenceEdition(Base, TenantMixin):
    __tablename__ = "conference_editions"
    __table_args__ = (UniqueConstraint("conference_id", "year"),)
    conference_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conferences.id"), index=True)
    year: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(400))
    official_cfp_url: Mapped[str | None] = mapped_column(String(2048))
    location: Mapped[str | None] = mapped_column(String(300))
    submission_url: Mapped[str | None] = mapped_column(String(2048))
    publication_outlet: Mapped[str | None] = mapped_column(String(400))
    publisher: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="exploratory")  # exploratory | official
    venue_confidence: Mapped[str] = mapped_column(String(20), default="unverified")
    venue_confidence_rationale: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column()
    latest_snapshot_id: Mapped[uuid.UUID | None] = mapped_column()


class Track(Base, TenantMixin):
    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("edition_id", "normalized_key"),)
    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conference_editions.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_key: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    paper_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    submission_categories: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    source_quote: Mapped[str | None] = mapped_column(Text)


class SourceSnapshot(Base, TenantMixin):
    __tablename__ = "source_snapshots"
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    edition_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conference_editions.id"), index=True)
    origin: Mapped[str] = mapped_column(String(30))  # fetched | researcher_supplied
    source_level: Mapped[str] = mapped_column(String(40), default="track_cfp")
    url: Mapped[str | None] = mapped_column(String(2048))
    final_url: Mapped[str | None] = mapped_column(String(2048))
    declared_origin: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artifacts.id"))
    text_artifact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    media_type: Mapped[str] = mapped_column(String(120))
    http_status: Mapped[int | None] = mapped_column(Integer)
    etag: Mapped[str | None] = mapped_column(String(400))
    last_modified: Mapped[str | None] = mapped_column(String(200))
    retrieved_at: Mapped[datetime] = mapped_column()
    effective_at: Mapped[datetime | None] = mapped_column()
    hops: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    scan_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rights_classification: Mapped[str] = mapped_column(String(60), default="public_web_page_internal_use")
    verification_status: Mapped[str] = mapped_column(String(40), default="unverified")
    verified_by: Mapped[uuid.UUID | None] = mapped_column()
    verified_at: Mapped[datetime | None] = mapped_column()
    verification_note: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(30), default="pending")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column()


class CfpRule(Base, TenantMixin):
    __tablename__ = "cfp_rules"
    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conference_editions.id"), index=True)
    track_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), index=True)
    item_type: Mapped[str] = mapped_column(String(20))  # rule | deadline
    rule_key: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(40))
    value_text: Mapped[str] = mapped_column(Text)
    value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(40))
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    quote: Mapped[str | None] = mapped_column(Text)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_level: Mapped[str] = mapped_column(String(40), default="track_cfp")
    methods: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    agreement: Mapped[str] = mapped_column(String(20))
    second_pass: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    problems: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    status: Mapped[str] = mapped_column(String(40), index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column()
    previous_rule_id: Mapped[uuid.UUID | None] = mapped_column()
    change_kind: Mapped[str | None] = mapped_column(String(20))  # new | unchanged | changed
    conflict_group: Mapped[str | None] = mapped_column(String(200))
    extractor_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column()


class DeadlineObligation(Base, TenantMixin):
    __tablename__ = "deadline_obligations"
    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conference_editions.id"), index=True)
    track_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tracks.id"))
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cfp_rules.id"), index=True)
    deadline_kind: Mapped[str] = mapped_column(String(40))
    governs_actions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    prerequisite_for: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    mandatory: Mapped[bool | None] = mapped_column(Boolean)
    stated_date: Mapped[str | None] = mapped_column(String(20))
    stated_time: Mapped[str | None] = mapped_column(String(20))
    stated_timezone: Mapped[str | None] = mapped_column(String(80))
    due_at: Mapped[datetime | None] = mapped_column()
    applicability: Mapped[str] = mapped_column(String(20), default="applies")  # applies | not_applicable | unknown
    status: Mapped[str] = mapped_column(String(40))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    human_resolution_id: Mapped[uuid.UUID | None] = mapped_column()


class RuleResolution(Base, TenantMixin):
    """A researcher's signed resolution of an ambiguous, conflicting or unverified rule."""

    __tablename__ = "rule_resolutions"
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cfp_rules.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # confirm | reject | edit | not_applicable
    resolved_value_text: Mapped[str | None] = mapped_column(Text)
    resolved_value: Mapped[str | None] = mapped_column(Text)
    resolved_timezone: Mapped[str | None] = mapped_column(String(80))
    resolved_time: Mapped[str | None] = mapped_column(String(20))
    rationale: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    rule_hash: Mapped[str] = mapped_column(String(64))


# --------------------------------------------------------------------------- M2 discovery & monitoring
from ..base import GlobalMixin  # noqa: E402


class VenueRegistryEntry(Base, GlobalMixin):
    """Curated official-source registry (global reference data; ingestion/admin role writes only)."""

    __tablename__ = "venue_registry"
    __scope__ = "global"
    series_key: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(400))
    acronym: Mapped[str | None] = mapped_column(String(40))
    organizer: Mapped[str | None] = mapped_column(String(300))
    publisher: Mapped[str | None] = mapped_column(String(200))
    homepage_url: Mapped[str] = mapped_column(String(2048))
    cfp_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    feed_urls: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    disciplines: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified_seed")  # verified | unverified_seed | retired
    verified_by: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column()
    questionable_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class ResearchProfile(Base, TenantMixin):
    __tablename__ = "research_profiles"
    __table_args__ = (UniqueConstraint("user_id", "project_id"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ConferenceCandidate(Base, TenantMixin):
    __tablename__ = "conference_candidates"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column()
    registry_entry_id: Mapped[uuid.UUID | None] = mapped_column()
    dedupe_key: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(400))
    acronym: Mapped[str | None] = mapped_column(String(40))
    year: Mapped[int | None] = mapped_column(Integer)
    official_url: Mapped[str] = mapped_column(String(2048))
    snapshot_artifact_id: Mapped[uuid.UUID | None] = mapped_column()
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    tracks: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    deadlines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    location: Mapped[str | None] = mapped_column(String(300))
    publisher: Mapped[str | None] = mapped_column(String(200))
    total_score: Mapped[float] = mapped_column()
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    questionable_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | imported | dismissed
    rank: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class CfpMonitorCheck(Base, TenantMixin):
    __tablename__ = "cfp_monitor_checks"
    edition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conference_editions.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column()
    url: Mapped[str] = mapped_column(String(2048))
    outcome: Mapped[str] = mapped_column(String(30))  # not_modified | unchanged | changed | failed
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column()
    detail: Mapped[str | None] = mapped_column(Text)
