"""Task kinds: which Temporal workflow runs them, on which task queue, with what retry/timeout policy."""

from __future__ import annotations

from dataclasses import dataclass

QUEUE_RESEARCH = "research-main"
QUEUE_FETCH = "controlled-fetch"
QUEUE_LATEX = "latex-sandbox"
QUEUE_EXPERIMENT = "experiment-sandbox"


@dataclass(frozen=True)
class TaskKindSpec:
    kind: str
    workflow: str
    task_queue: str
    max_attempts: int = 3
    timeout_seconds: int = 1800
    compensation: str | None = None
    owner_label: str = "platform"
    billable: bool = False
    description: str = ""


_SPECS = [
    TaskKindSpec("cfp_import", "CfpImportWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Controlled fetch of an official CFP, snapshot, extraction and independent validation"),
    TaskKindSpec("cfp_extract_supplied", "CfpImportWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Extraction and validation of a researcher-supplied official CFP document"),
    TaskKindSpec("cfp_monitor", "CfpMonitorWorkflow", QUEUE_RESEARCH, description="Conditional refetch and change detection"),
    TaskKindSpec("conference_discovery", "ConferenceDiscoveryWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Discovery from the curated official-source registry and relevance ranking"),
    TaskKindSpec("template_import", "TemplateImportWorkflow", QUEUE_RESEARCH,
                 description="Retrieve and safely analyse an official LaTeX template archive"),
    TaskKindSpec("template_compile", "CompileWorkflow", QUEUE_LATEX, timeout_seconds=900,
                 description="Sandboxed sample/manuscript compilation"),
    TaskKindSpec("literature_search", "LiteratureSearchWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Search permitted scholarly providers, normalise, deduplicate, locate permitted full text"),
    TaskKindSpec("evidence_extraction", "EvidenceExtractionWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Extract claims, methods, results and passages from permitted full text"),
    TaskKindSpec("opportunity_generation", "OpportunityWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Gap proposals, closest work, study-type advice, rationale and feasibility"),
    TaskKindSpec("claim_support_check", "ClaimSupportWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Model-assisted passage support assessment for a claim/evidence pair"),
    TaskKindSpec("methodology_review", "MethodologyReviewWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Independent methodology review of a draft protocol"),
    TaskKindSpec("result_assessment", "ResultAssessmentWorkflow", QUEUE_RESEARCH,
                 description="Deterministic checks of a researcher-supplied result manifest"),
    TaskKindSpec("manuscript_generation", "ManuscriptGenerationWorkflow", QUEUE_RESEARCH, billable=True,
                 timeout_seconds=3600, description="Evidence-grounded section generation against a frozen manifest"),
    TaskKindSpec("review_run", "ReviewWorkflow", QUEUE_RESEARCH, billable=True, timeout_seconds=3600,
                 description="Independent scientific, citation/evidence, compliance review and meta-review"),
    TaskKindSpec("manuscript_compile", "CompileWorkflow", QUEUE_LATEX, timeout_seconds=900,
                 description="Compile the manuscript in the official template and run machine checks"),
    TaskKindSpec("integrity_check", "IntegrityWorkflow", QUEUE_RESEARCH, description="Cross-stage research integrity checks"),
    TaskKindSpec("package_build", "PackageWorkflow", QUEUE_LATEX, timeout_seconds=900,
                 description="Build and verify the content-manifest-bound submission package"),
    TaskKindSpec("experiment_run", "ExperimentRunWorkflow", QUEUE_EXPERIMENT, max_attempts=1, timeout_seconds=7200,
                 billable=True, description="Approved sandboxed computational run"),
    TaskKindSpec("experiment_recompute", "RecomputationWorkflow", QUEUE_EXPERIMENT, timeout_seconds=1800,
                 description="Independent metric recomputation from raw outputs"),
    TaskKindSpec("systematic_search", "SystematicSearchWorkflow", QUEUE_RESEARCH, billable=True,
                 description="Protocol-bound reproducible search for a systematic/mapping/scoping/tertiary review"),
    TaskKindSpec("artifact_reconcile", "ReconcileWorkflow", QUEUE_RESEARCH, description="Orphan/temporary object reconciliation"),
]

TASK_KINDS: dict[str, TaskKindSpec] = {s.kind: s for s in _SPECS}
