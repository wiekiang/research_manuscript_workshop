"""Study-type taxonomy and versioned ResearchWorkflowDefinitions (PRODUCT_SPEC §2.4, §2.7, §3).

Definitions are immutable once published: a change is a new `definition_version`. `enabled_for_submission_ready`
is false for methods whose search/screening/appraisal/synthesis/reporting workflows have not passed
method-specific validation; such methods may be planned but can never reach APPROVED_FOR_EXPORT.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StageDefinition(BaseModel):
    id: str
    title: str
    description: str
    predecessor_stage_ids: list[str] = Field(default_factory=list)
    input_artifact_kinds: list[str] = Field(default_factory=list)
    output_artifact_kinds: list[str] = Field(default_factory=list)
    validator_ids: list[str] = Field(default_factory=list)
    waits_for_human: bool = False
    retry_policy_id: str = "default"
    automation: str = "manual"  # manual | assisted | automated


class ResearchWorkflowDefinition(BaseModel):
    id: str
    definition_version: int
    study_type: str
    title: str
    plain_definition: str
    enabled_for_submission_ready: bool
    availability: str
    planning_only_reason: str | None = None
    required_stages: list[StageDefinition]
    optional_stages: list[StageDefinition] = Field(default_factory=list)
    approval_gates: list[str] = Field(default_factory=lambda: ["H1", "H2", "H3", "H4"])
    validation_rule_ids: list[str] = Field(default_factory=list)
    required_artifact_kinds: list[str] = Field(default_factory=list)
    h3_validation: list[str] = Field(default_factory=list)
    reporting_standard: str | None = None
    protocol_sections: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.id}@{self.definition_version}"


VENUE_CATEGORIES = {
    "full_paper": "A full-length conference paper in a main research track.",
    "short_paper": "A shorter paper reporting focused or preliminary work.",
    "industry_experience_report": "A report of practice or deployment experience (industry/experience track).",
    "workshop_paper": "A paper for a co-located workshop.",
    "poster": "A poster or extended abstract.",
    "demo": "A demonstration of a tool or system.",
    "other": "Another category explicitly listed in the CFP.",
}

COMMON_PROTOCOL = ["research_questions", "hypotheses", "operational_definitions", "sample_or_data_selection",
                   "inclusion_exclusion", "baselines", "metrics", "analysis_plan", "statistical_tests",
                   "power_or_uncertainty", "leakage_controls", "limitations", "compute_estimate", "reproducibility_plan",
                   "ethics_rights_declaration"]


def _s(id_, title, desc, preds=(), outs=("method_stage_output",), validators=(), human=False, automation="manual"):
    return StageDefinition(id=id_, title=title, description=desc, predecessor_stage_ids=list(preds),
                           output_artifact_kinds=list(outs), validator_ids=list(validators), waits_for_human=human,
                           automation=automation)


EMPIRICAL_STAGES = [
    _s("data_provenance", "Data provenance and selection",
       "Declare data origin, rights, licence, PII classification and selection criteria for the supplied data.",
       outs=("method_stage_output",), validators=("v.data_provenance_complete", "v.rights_declared")),
    _s("analysis", "Approved analysis or experiment (researcher-supplied)",
       "Upload the result manifest produced by the analysis that follows the frozen protocol.",
       preds=("data_provenance",), outs=("result_manifest",), validators=("v.result_manifest_complete",)),
    _s("result_checks", "Statistical and result checks",
       "Deterministic consistency checks and assurance assessment of the supplied results.",
       preds=("analysis",), outs=("result_assessment",), validators=("v.assurance_assessed",), automation="assisted"),
]

DEFINITIONS: list[ResearchWorkflowDefinition] = [
    ResearchWorkflowDefinition(
        id="empirical_quantitative", definition_version=1, study_type="empirical_quantitative",
        title="Primary empirical quantitative study",
        plain_definition="Original measurements or experiments analysed quantitatively to answer the research questions.",
        enabled_for_submission_ready=True, availability="M8 with researcher-supplied results; platform runs in M9",
        required_stages=EMPIRICAL_STAGES, validation_rule_ids=["v.protocol_complete", "v.assurance_assessed"],
        required_artifact_kinds=["protocol", "result_manifest", "result_assessment"],
        h3_validation=["raw result or declared aggregate with assurance level", "protocol adherence", "uncertainty",
                       "interpretation"], protocol_sections=COMMON_PROTOCOL),
    ResearchWorkflowDefinition(
        id="secondary_data", definition_version=1, study_type="secondary_data",
        title="Secondary quantitative data analysis",
        plain_definition="New quantitative analysis of an existing dataset collected by others.",
        enabled_for_submission_ready=True, availability="M8 with researcher-supplied results",
        required_stages=EMPIRICAL_STAGES, validation_rule_ids=["v.protocol_complete", "v.assurance_assessed"],
        required_artifact_kinds=["protocol", "result_manifest", "result_assessment"],
        h3_validation=["data licence and provenance", "analysis follows protocol", "uncertainty"],
        protocol_sections=COMMON_PROTOCOL),
    ResearchWorkflowDefinition(
        id="theoretical", definition_version=1, study_type="theoretical", title="Theoretical contribution",
        plain_definition="A new theory, model, proof or conceptual framework with an argument evaluated as the field expects.",
        enabled_for_submission_ready=True, availability="M8 where the venue accepts theoretical papers",
        required_stages=[
            _s("conceptual_framework", "Conceptual framework", "State definitions, assumptions and scope.",
               validators=("v.assumptions_stated",)),
            _s("derivation", "Derivation or argument", "Record the derivation, proof or argument steps.",
               preds=("conceptual_framework",), validators=("v.argument_recorded",)),
            _s("evaluation", "Counterexample or field-appropriate evaluation",
               "Document counterexample search, consistency checks or the evaluation the field expects.",
               preds=("derivation",), validators=("v.evaluation_recorded",)),
        ], validation_rule_ids=["v.protocol_complete"], required_artifact_kinds=["protocol", "method_stage_output"],
        h3_validation=["logical consistency", "assumptions", "scope of claims"],
        protocol_sections=["research_questions", "assumptions", "definitions", "argument_plan", "evaluation_plan",
                           "limitations", "ethics_rights_declaration"]),
    ResearchWorkflowDefinition(
        id="methodological", definition_version=1, study_type="methodological", title="Methodological contribution",
        plain_definition="A new method, technique or tool with an appropriate evaluation.",
        enabled_for_submission_ready=True, availability="M8 with supplied evaluation; automated execution in M9",
        required_stages=[
            _s("method_specification", "Method specification", "Specify the method precisely.",
               validators=("v.method_specified",)),
            _s("implementation", "Implementation or formal account", "Code, pseudo-code or formal account of the method.",
               preds=("method_specification",), validators=("v.implementation_recorded",)),
            _s("evaluation", "Evaluation (researcher-supplied results)", "Comparison against baselines per protocol.",
               preds=("implementation",), outs=("result_manifest",), validators=("v.result_manifest_complete",)),
            _s("result_checks", "Result checks", "Assurance assessment of the evaluation results.",
               preds=("evaluation",), outs=("result_assessment",), validators=("v.assurance_assessed",),
               automation="assisted"),
        ], validation_rule_ids=["v.protocol_complete", "v.assurance_assessed"],
        required_artifact_kinds=["protocol", "result_manifest", "result_assessment"],
        h3_validation=["comparison", "reproducibility or proof checks"], protocol_sections=COMMON_PROTOCOL),
    ResearchWorkflowDefinition(
        id="narrative_review", definition_version=1, study_type="narrative_review", title="Narrative literature review",
        plain_definition="A critical synthesis of selected literature that advances an original argument. It is not "
                         "a systematic review and must not be labelled as one.",
        enabled_for_submission_ready=True, availability="M8 only when the selected track accepts it",
        required_stages=[
            _s("documented_selection", "Documented selection", "Record searches, sources and why works were selected.",
               validators=("v.selection_documented",)),
            _s("critical_synthesis", "Critical synthesis", "Synthesise and critique the selected literature.",
               preds=("documented_selection",), validators=("v.synthesis_recorded",)),
            _s("original_argument", "Original argument", "State the original argument the review makes.",
               preds=("critical_synthesis",), validators=("v.original_argument_recorded",)),
        ], validation_rule_ids=["v.protocol_complete", "v.coverage_reported"],
        required_artifact_kinds=["protocol", "coverage_assessment", "method_stage_output"],
        h3_validation=["source coverage", "balance", "interpretation"],
        protocol_sections=["review_question", "sources_and_search_strategy", "selection_rationale", "synthesis_approach",
                           "limitations", "ethics_rights_declaration"]),
    ResearchWorkflowDefinition(
        id="empirical_qualitative", definition_version=1, study_type="empirical_qualitative",
        title="Primary empirical qualitative study",
        plain_definition="Interviews, observation or documents analysed qualitatively (e.g. thematic analysis).",
        enabled_for_submission_ready=False, availability="Planning only until M10 validation",
        planning_only_reason="the ethics, collection, coding audit-trail and analysis workflow has not passed "
                             "method-specific validation",
        required_stages=[
            _s("ethics_rights", "Ethics and rights", "External ethics approval and consent records.", human=True),
            _s("collection", "Authorized collection", "Collection under the approved protocol.", preds=("ethics_rights",)),
            _s("coding", "Coding with audit trail", "Codebook and source-to-code trace.", preds=("collection",)),
            _s("analysis", "Thematic or other analysis", "Analysis and researcher interpretation.", preds=("coding",)),
        ], h3_validation=["source-to-code trace", "researcher interpretation", "limitations"],
        protocol_sections=COMMON_PROTOCOL),
    ResearchWorkflowDefinition(
        id="systematic_review", definition_version=1, study_type="systematic_review",
        title="Systematic review", reporting_standard="PRISMA 2020 (SEGRESS for software engineering)",
        plain_definition="A protocol-driven, reproducible search, screening, appraisal and synthesis of all eligible studies.",
        enabled_for_submission_ready=False, availability="Planning only until M10 validation",
        planning_only_reason="search, screening, appraisal, synthesis and reporting workflows have not passed "
                             "method-specific validation",
        required_stages=[
            _s("frozen_protocol", "Frozen review protocol", "Registered/frozen protocol with criteria.", human=True),
            _s("search", "Reproducible search", "Exact queries, sources and dates.", preds=("frozen_protocol",)),
            _s("screening", "Screening", "Title/abstract and full-text screening with reasons.", preds=("search",), human=True),
            _s("appraisal_extraction", "Appraisal and extraction", "Risk-of-bias appraisal and data extraction forms.",
               preds=("screening",)),
            _s("synthesis", "Synthesis", "Narrative or quantitative synthesis per protocol.", preds=("appraisal_extraction",)),
        ], h3_validation=["search and extraction audit", "synthesis and reporting checks"]),
    ResearchWorkflowDefinition(
        id="meta_analysis", definition_version=1, study_type="meta_analysis", title="Meta-analysis",
        reporting_standard="PRISMA 2020",
        plain_definition="A systematic review that statistically pools effect estimates across studies.",
        enabled_for_submission_ready=False, availability="Planning only until M10 validation",
        planning_only_reason="pooling and heterogeneity analysis workflows are not validated",
        required_stages=[
            _s("frozen_protocol", "Frozen review protocol", "Protocol with effect measures and pooling model.", human=True),
            _s("search", "Reproducible search", "Exact queries, sources and dates.", preds=("frozen_protocol",)),
            _s("screening", "Screening", "Screening with reasons.", preds=("search",), human=True),
            _s("extraction", "Effect extraction", "Extract effect sizes and variances.", preds=("screening",)),
            _s("pooling", "Pooling and heterogeneity", "Statistical pooling per protocol.", preds=("extraction",)),
        ], h3_validation=["extraction audit", "pooling checks", "heterogeneity and bias assessment"]),
    ResearchWorkflowDefinition(
        id="mapping_review", definition_version=1, study_type="mapping_review", title="Systematic mapping study",
        plain_definition="A protocol-driven classification of a research area to map what has been studied.",
        enabled_for_submission_ready=False, availability="Planning only until M10 validation",
        planning_only_reason="classification/charting workflow not validated",
        required_stages=[
            _s("frozen_protocol", "Frozen protocol", "Protocol and classification scheme.", human=True),
            _s("search", "Search", "Reproducible search.", preds=("frozen_protocol",)),
            _s("screening", "Screening", "Screening with reasons.", preds=("search",), human=True),
            _s("charting", "Classification and charting", "Chart studies against the scheme.", preds=("screening",)),
            _s("map", "Map and interpretation", "Map of the area and interpretation.", preds=("charting",)),
        ], h3_validation=["taxonomy and charting audit", "method-specific report"]),
    ResearchWorkflowDefinition(
        id="scoping_review", definition_version=1, study_type="scoping_review", title="Scoping review",
        reporting_standard="PRISMA-ScR",
        plain_definition="A protocol-driven overview of the extent and nature of evidence on a broad question.",
        enabled_for_submission_ready=False, availability="Planning only until M10 validation",
        planning_only_reason="charting workflow and PRISMA-ScR reporting checks not validated",
        required_stages=[
            _s("frozen_protocol", "Frozen protocol", "Protocol.", human=True),
            _s("search", "Search", "Reproducible search.", preds=("frozen_protocol",)),
            _s("screening", "Screening", "Screening with reasons.", preds=("search",), human=True),
            _s("charting", "Charting", "Data charting.", preds=("screening",)),
            _s("map", "Summary and interpretation", "Summary of evidence.", preds=("charting",)),
        ], h3_validation=["charting audit", "PRISMA-ScR items"]),
    ResearchWorkflowDefinition(
        id="tertiary_review", definition_version=1, study_type="tertiary_review", title="Tertiary review (review of reviews)",
        plain_definition="A protocol-driven synthesis of existing systematic reviews.",
        enabled_for_submission_ready=False, availability="Planning only until M10 validation",
        planning_only_reason="review-level selection, overlap and quality assessment not validated",
        required_stages=[
            _s("frozen_protocol", "Frozen protocol", "Protocol.", human=True),
            _s("search", "Search for eligible reviews", "Reproducible search.", preds=("frozen_protocol",)),
            _s("appraisal_extraction", "Appraisal and extraction", "Quality and overlap assessment.", preds=("search",)),
            _s("synthesis", "Synthesis of reviews", "Synthesis.", preds=("appraisal_extraction",)),
        ], h3_validation=["review-level selection", "overlap and quality assessment"]),
    ResearchWorkflowDefinition(
        id="computational_experiment", definition_version=1, study_type="computational_experiment",
        title="Platform-executed computational study",
        plain_definition="An approved computational protocol executed by the platform in an isolated sandbox.",
        enabled_for_submission_ready=False, availability="M9 (sandboxed execution)",
        planning_only_reason="enabled when M9 sandboxed execution and independent recomputation pass",
        required_stages=[
            _s("environment", "Pinned environment and inputs", "Image digest, lockfile, input hashes.",
               outs=("experiment_code", "experiment_input")),
            _s("run", "Sandboxed run", "Approved run with seeds and limits.", preds=("environment",),
               outs=("run_manifest", "experiment_raw_output", "experiment_log"), automation="automated"),
            _s("recompute", "Independent metric recomputation", "Separate validator recomputes metrics.",
               preds=("run",), outs=("recomputation_report",), automation="automated"),
        ], h3_validation=["run manifest", "recomputed metrics", "tolerances", "failed runs disclosed"]),
]

# M9 enablement as a new immutable version: sandboxed execution, independent recomputation and reproduction passed
# their acceptance tests (tests/workflows/test_m9_experiments.py). Instances on version 1 stay planning-only.
_ce1 = next(d for d in DEFINITIONS if d.id == "computational_experiment")
DEFINITIONS.append(_ce1.model_copy(update={
    "definition_version": 2, "enabled_for_submission_ready": True, "availability": "M9 (sandboxed execution enabled)",
    "planning_only_reason": None}))

# M10 enablement as new immutable versions: each stage is bound to a validator that checks stored records (search
# runs, screening decisions, extraction/appraisal, deterministic synthesis, verbatim-coded segments), validated by
# tests/workflows/test_m10_methods.py and contracts/tests/test_synthesis.py. Version 1 instances stay planning-only.
_M10_VALIDATORS = {
    "frozen_protocol": ("v.review_spec_valid",), "search": ("v.search_reproducible",),
    "screening": ("v.screening_complete",), "appraisal_extraction": ("v.extraction_complete",),
    "extraction": ("v.extraction_complete",), "charting": ("v.extraction_complete",),
    "pooling": ("v.meta_analysis_recomputed",), "map": ("v.map_computed",),
    "ethics_rights": ("v.ethics_approval_recorded",), "collection": ("v.collection_documented",),
    "coding": ("v.codebook_trace",), "analysis": ("v.themes_traced",),
}
_M10_SYNTHESIS = {"systematic_review": ("v.narrative_synthesis",), "tertiary_review": ("v.overlap_assessed",)}
for _id in ("systematic_review", "meta_analysis", "mapping_review", "scoping_review", "tertiary_review",
            "empirical_qualitative"):
    _d1 = next(d for d in DEFINITIONS if d.id == _id and d.definition_version == 1)
    _stages = []
    for _st in _d1.required_stages:
        _v = _M10_SYNTHESIS.get(_id) if _st.id == "synthesis" else _M10_VALIDATORS.get(_st.id, ())
        _stages.append(_st.model_copy(update={"validator_ids": list(_v or ())}))
    if _id == "tertiary_review":  # review-level selection is a required, validated stage
        _sel = _s("screening", "Review-level selection", "Screen candidate reviews with protocol reasons.",
                  preds=("search",), validators=("v.screening_complete",), human=True)
        _stages = [_stages[0], _stages[1], _sel] + [x.model_copy(update={"predecessor_stage_ids": ["screening"]})
                                                     if x.id == "appraisal_extraction" else x for x in _stages[2:]]
    _sections = list(_d1.protocol_sections or COMMON_PROTOCOL)
    if _id != "empirical_qualitative":
        _sections.append("review_specification")
    DEFINITIONS.append(_d1.model_copy(update={
        "definition_version": 2, "enabled_for_submission_ready": True, "planning_only_reason": None,
        "availability": "M10 (method-specific validation passed)", "required_stages": _stages,
        "protocol_sections": _sections}))

REGISTRY: dict[str, ResearchWorkflowDefinition] = {d.key: d for d in DEFINITIONS}


def latest(study_type: str) -> ResearchWorkflowDefinition:
    cands = [d for d in DEFINITIONS if d.study_type == study_type]
    if not cands:
        raise KeyError(study_type)
    return max(cands, key=lambda d: d.definition_version)


def publish(defn: ResearchWorkflowDefinition) -> None:
    """Publish a new immutable definition version (used by later milestones, e.g. M9/M10 enablement)."""
    if defn.key in REGISTRY:
        raise ValueError(f"{defn.key} already published; definitions are immutable")
    DEFINITIONS.append(defn)
    REGISTRY[defn.key] = defn


EXPORT = [ResearchWorkflowDefinition, StageDefinition]
