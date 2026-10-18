"""Artifact kinds and the reservation/commit protocol contracts (PRODUCT_SPEC §3, artifact publication)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import ArtifactStatus, DataClassification, Freshness, ReservationStatus

MB = 1024 * 1024
JSON = ("application/json",)
TEXT = ("text/plain",)


@dataclass(frozen=True)
class ArtifactKindSpec:
    kind: str
    media_types: tuple[str, ...]
    max_bytes: int
    default_classification: DataClassification
    worker_producible: bool = True
    description: str = ""


_KINDS = [
    # M0 / generic
    ArtifactKindSpec("generic_json", JSON, 5 * MB, DataClassification.INTERNAL, description="Schema-validated JSON"),
    ArtifactKindSpec("model_output", JSON, 5 * MB, DataClassification.INTERNAL, description="Validated agent output"),
    # M1 CFP
    ArtifactKindSpec(
        "source_snapshot",
        ("text/html", "application/pdf", "text/plain", "application/xhtml+xml"),
        25 * MB,
        DataClassification.PUBLIC,
        description="Quarantined, scanned official source bytes",
    ),
    ArtifactKindSpec("source_text", ("application/json", "text/plain"), 20 * MB, DataClassification.PUBLIC, description="Located text extracted from a snapshot"),
    ArtifactKindSpec("cfp_extraction", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("cfp_validation", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("cfp_ruleset", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("deadline_schedule", JSON, 2 * MB, DataClassification.INTERNAL, worker_producible=False),
    # M2 discovery
    ArtifactKindSpec("discovery_result", JSON, 5 * MB, DataClassification.INTERNAL),
    # M3 templates
    ArtifactKindSpec("template_archive", ("application/zip",), 50 * MB, DataClassification.PUBLIC),
    ArtifactKindSpec("template_manifest", JSON, 2 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("compile_report", JSON, 2 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("compiled_pdf", ("application/pdf",), 50 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("compile_log", TEXT, 10 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("latex_source_bundle", ("application/zip",), 50 * MB, DataClassification.INTERNAL),
    # M4 literature
    ArtifactKindSpec("search_run_record", JSON, 20 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec(
        "paper_fulltext", ("application/pdf", "application/xml", "text/xml", "text/html", "text/plain"), 50 * MB,
        DataClassification.INTERNAL,
    ),
    ArtifactKindSpec("evidence_extraction", JSON, 10 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("coverage_assessment", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("opportunity_set", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("paper_rationale", JSON, 2 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("feasibility_assessment", JSON, 2 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("study_type_recommendation", JSON, 2 * MB, DataClassification.INTERNAL),
    # M5 contribution
    ArtifactKindSpec("research_direction", JSON, 2 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("protocol", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("methodology_review", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec(
        "contribution_file",
        (
            "text/csv", "application/json", "text/plain", "text/markdown", "application/pdf",
            "text/x-python", "application/x-ipynb+json", "application/zip", "image/png", "image/svg+xml",
            "application/x-tex", "text/x-tex",
        ),
        200 * MB,
        DataClassification.RESTRICTED,
        worker_producible=False,
    ),
    ArtifactKindSpec("result_manifest", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("result_assessment", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("contribution_matrix", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("method_stage_output", JSON, 20 * MB, DataClassification.INTERNAL),
    # M6 manuscript
    ArtifactKindSpec("manuscript_version", JSON, 20 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("generation_candidate", JSON, 20 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("manuscript_brief", JSON, 20 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("figure", ("image/png", "application/pdf", "image/svg+xml"), 20 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("bibliography", ("application/x-bibtex", "text/plain"), 5 * MB, DataClassification.INTERNAL),
    # M7 review
    ArtifactKindSpec("review_report", JSON, 10 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("meta_review", JSON, 10 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("compliance_report", JSON, 10 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("integrity_report", JSON, 10 * MB, DataClassification.INTERNAL),
    # M8 submission
    ArtifactKindSpec("eligibility_assessment", JSON, 2 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("readiness_assessment", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("content_manifest", JSON, 5 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("author_record", JSON, 2 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("disclosure_statement", JSON, 2 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("export_package", ("application/zip",), 200 * MB, DataClassification.INTERNAL),
    # M9 experiments
    ArtifactKindSpec("experiment_code", ("application/zip", "text/x-python"), 50 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("experiment_input", ("text/csv", "application/json", "application/zip", "text/plain"), 200 * MB, DataClassification.RESTRICTED, worker_producible=False),
    ArtifactKindSpec("experiment_raw_output", ("application/zip", "application/json", "text/csv", "text/plain"), 200 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("experiment_log", TEXT, 20 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("run_manifest", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("recomputation_report", JSON, 5 * MB, DataClassification.INTERNAL),
    ArtifactKindSpec("experiment_plan", JSON, 2 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("environment_manifest", JSON, 2 * MB, DataClassification.INTERNAL),
    # M10 evidence synthesis / qualitative
    ArtifactKindSpec("synthesis_record", JSON, 10 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("review_appendix", JSON, 10 * MB, DataClassification.INTERNAL, worker_producible=False),
    ArtifactKindSpec("qualitative_codebook", JSON, 10 * MB, DataClassification.RESTRICTED, worker_producible=False),
]

ARTIFACT_KINDS: dict[str, ArtifactKindSpec] = {k.kind: k for k in _KINDS}


class ReservationRequest(BaseModel):
    project_id: UUID | None = None
    task_id: UUID | None = None
    input_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_kind: str
    media_type: str
    expected_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    classification: DataClassification | None = None
    label: str | None = Field(default=None, max_length=300)
    # Distinguishes several outputs of the same kind produced by one task (e.g. "snapshot:2").
    slot: str = Field(default="0", max_length=120)


class ReservationResponse(BaseModel):
    reservation_id: UUID
    idempotency_key: str
    status: ReservationStatus
    upload_url: str
    upload_method: str = "PUT"
    artifact_id: UUID | None = None
    expires_at: datetime


class CommitRequest(BaseModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    depends_on: list[UUID] = Field(default_factory=list)
    dependency_kind: str = "derived_from"
    validator_version: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ArtifactOut(BaseModel):
    id: UUID
    project_id: UUID | None
    kind: str
    content_hash: str
    size_bytes: int
    media_type: str
    status: ArtifactStatus
    freshness: Freshness
    classification: DataClassification
    label: str | None = None
    created_at: datetime
    committed_at: datetime | None = None
    task_id: UUID | None = None
    input_manifest_hash: str | None = None
