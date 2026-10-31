/**
 * Response shapes returned by the API. Most endpoints return hand-built JSON (not response models), so these types
 * mirror apps/api/src/rp_api/routers/*.py and features/*.py. Keep them in sync when those change.
 */

export type ProjectState =
    | "CREATED"
    | "TARGET_REVIEW"
    | "DIRECTION_REVIEW"
    | "PROTOCOL_REVIEW"
    | "RESEARCH_ACTIVE"
    | "OUTCOME_REVIEW"
    | "DRAFTING"
    | "SCIENTIFIC_REVIEW"
    | "COMPLIANCE_REVIEW"
    | "FINAL_APPROVAL"
    | "APPROVED_FOR_EXPORT"
    | "PACKAGE_READY"
    | "PAUSED"
    | "BLOCKED"
    | "CANCELLED";

export interface TokenBody {
    access_token: string;
    token_type: string;
    expires_in: number;
    user: { id: string; email: string; display_name: string };
    tenant_id: string | null;
    tenant_role: string | null;
}

export interface Me {
    user: {
        id: string;
        email: string;
        display_name: string;
        mfa_enabled: boolean;
        responsibility_acknowledged: boolean;
        responsibility_ack_at: string | null;
    };
    session: { mfa: boolean; tenant_id: string | null };
    workspaces: { tenant_id: string; name: string; slug: string; role: string }[];
    responsibility: { message: string; version: string };
}

export interface GateResult {
    gate_id: string;
    passed: boolean;
    reasons: string[];
    evidence: Record<string, unknown>;
    next_action: string | null;
}

export interface NextStep {
    target_state: string | null;
    description?: string;
    overlay?: string;
    message?: string;
    gates: GateResult[];
    ready?: boolean;
}

export interface BudgetStatus {
    cap_cents: number;
    spent_cents: number;
    reserved_cents: number;
    remaining_cents: number;
    currency: string;
    percent_used: number;
}

export interface ApprovalSummary {
    gate: string;
    status: string;
    approval_id: string;
    decided_at: string;
    invalidation_reason: string | null;
}

export interface Project {
    id: string;
    title: string;
    topic: string | null;
    description: string | null;
    state: ProjectState;
    resume_state: ProjectState | null;
    overlay_reason: string | null;
    version: number;
    readiness_stage: string;
    target_mode: "official" | "exploratory" | null;
    target_track_id: string | null;
    target_edition_id: string | null;
    method_instance_id: string | null;
    budget_cap_cents: number;
    currency: string;
    my_role: string | null;
    created_at: string;
    updated_at: string;
    next_step?: NextStep | null;
    approvals?: ApprovalSummary[];
    /** Detail endpoint: the waiting tasks; list endpoint: their count. */
    waiting_human_tasks?: { id: string; kind: string; reason: string | null }[] | number;
    budget?: BudgetStatus;
    responsibility_message?: string;
}

export interface TransitionResult {
    project_id: string;
    from_state: string;
    state: string;
    version: number;
    event_id: string;
    replayed: boolean;
    gate_results: GateResult[];
}

export interface Task {
    id: string;
    kind: string;
    state: string;
    attempt: number;
    max_attempts: number;
    owner: string;
    error_code: string | null;
    error_message: string | null;
    waiting_reason: string | null;
    progress: Record<string, unknown>;
    result: Record<string, unknown>;
    output_artifact_ids: string[];
    created_at: string;
    updated_at: string;
    started_at: string | null;
    finished_at: string | null;
    estimated_cost_cents: number | null;
    params: Record<string, unknown>;
}

export interface ProjectEvent {
    id: string;
    seq: number;
    type: string;
    from_state: string | null;
    to_state: string | null;
    version: number | null;
    actor_type: string;
    actor_id: string;
    occurred_at: string;
    payload: Record<string, unknown>;
    gate_results: { results?: GateResult[] } & Record<string, unknown>;
    output_artifact_ids: string[];
    human_approval_id: string | null;
}

export interface Artifact {
    id: string;
    project_id: string | null;
    kind: string;
    content_hash: string;
    size_bytes: number;
    media_type: string;
    status: string;
    freshness: "current" | "stale";
    classification: string;
    label: string | null;
    rights: Record<string, unknown>;
    metadata: Record<string, unknown>;
    created_by: string;
    created_at: string;
    committed_at: string | null;
    stale_reason: string | null;
    task_id: string | null;
}

export interface Locator {
    char_start: number;
    char_end: number;
    section: string | null;
    page: number | null;
}

export interface CfpObservation {
    method: string;
    quote: string;
    locator: Locator | null;
    quote_problem: string | null;
    value: string | null;
    date: string | null;
    time: string | null;
    timezone: string | null;
    value_text: string | null;
    /** Present on model_assisted observations: the model provider that produced them (e.g. "fixture"). */
    provider?: string | null;
    provenance_label?: string | null;
}

export interface CfpRule {
    id: string;
    item_type: "rule" | "deadline";
    rule_key: string;
    category: string;
    track_id: string | null;
    track: string | null;
    value_text: string;
    value: string | null;
    unit: string | null;
    blocking: boolean;
    quote: string | null;
    locator: Locator | null;
    source_level: string;
    snapshot_id: string;
    methods: string[];
    verification_methods: string[];
    agreement: string;
    second_pass: { verdict?: string; issue?: string | null } & Record<string, unknown>;
    problems: string[];
    status: string;
    is_current: boolean;
    change_kind: string | null;
    conflict_group: string | null;
    observations: CfpObservation[];
    resolutions: {
        id: string;
        action: string;
        resolved_value_text: string | null;
        resolved_value: string | null;
        resolved_timezone: string | null;
        rationale: string;
        at: string;
    }[];
}

export interface Deadline {
    id: string;
    rule_id: string;
    deadline_kind: string;
    track: string | null;
    stated_date: string | null;
    stated_time: string | null;
    stated_timezone: string | null;
    due_at: string | null;
    mandatory: boolean | null;
    governs_actions: string[];
    applicability: string;
    status: string;
}

export interface Snapshot {
    id: string;
    origin: "fetched" | "researcher_supplied";
    source_level: string;
    url: string | null;
    final_url: string | null;
    artifact_id: string;
    content_hash: string;
    media_type: string;
    retrieved_at: string;
    verification_status: string;
    extraction_status: string;
    scan_report: { flags?: string[]; verdict?: string; antivirus?: string; sniffed_type?: string; robots?: string } & Record<string, unknown>;
    hops: { url: string; ip: string; status: number }[];
    declared_origin: string | null;
    rights_classification: string;
}

export interface EditionView {
    conference: { id: string; name: string; acronym: string | null; official_url: string | null; questionable_flag: boolean; questionable_evidence: unknown[] };
    edition: {
        id: string;
        name: string;
        year: number | null;
        status: string;
        location: string | null;
        official_cfp_url: string | null;
        submission_url: string | null;
        publication_outlet: string | null;
        venue_confidence: string;
    };
    tracks: { id: string; name: string; paper_types: string[]; description: string | null }[];
    rules: CfpRule[];
    deadlines: Deadline[];
    snapshots: Snapshot[];
    open_items: number;
    is_target: boolean;
}

export interface ProjectCfp {
    target: { mode: string | null; edition_id: string | null; track_id: string | null };
    editions: EditionView[];
    pending_snapshots: Snapshot[];
    gate: GateResult;
    declaration: { version: string; text: string };
    precedence: string[];
}

export interface LedgerEntry {
    id: string;
    user_id: string;
    contributor: string | null;
    category: string;
    summary: string;
    diff: string | null;
    artifact_id: string | null;
    source_action: string;
    auto_captured: boolean;
    rationale: string | null;
    rationale_requested: boolean;
    status: string;
    correction_of: string | null;
    verified_at: string | null;
    created_at: string;
}

export interface Usage {
    budget: BudgetStatus;
    stage_limits: Record<string, unknown>;
    by_category: { category: string; provider: string; billing_source: string; units: number; actual_cost_cents: number; estimated_cost_cents: number; entries: number }[];
    recent: { id: string; category: string; provider: string; units: number; unit: string; actual_cost_cents: number; estimated_cost_cents: number; billing_source: string; stage: string | null; occurred_at: string; unit_price_snapshot: Record<string, unknown> }[];
    model_invocations: {
        id: string;
        agent: string;
        provider: string;
        model: string;
        prompt_version: string;
        status: string;
        input_tokens: number | null;
        output_tokens: number | null;
        estimated_cost_cents: number;
        actual_cost_cents: number | null;
        data_classification: string;
        denial_reason: string | null;
        created_at: string;
    }[];
    alerts: { threshold_pct: number; cap_cents: number; spent_cents: number; at: string }[];
    cap_changes: { previous_cap_cents: number; new_cap_cents: number; rationale: string | null; at: string }[];
    note: string;
}

export interface DataFlow {
    attestation_text: string;
    data_kinds: string[];
    items: { id: string; provider_key: string; data_kinds: string[]; max_classification: string; attested_at: string; revoked_at: string | null }[];
}

export interface Notification {
    id: string;
    type: string;
    title: string;
    body: string | null;
    link: string | null;
    project_id: string | null;
    read_at: string | null;
    created_at: string;
}

export interface Member {
    user_id: string;
    email: string;
    display_name: string;
    role: string;
    is_corresponding_author: boolean;
}

export interface WorkspaceMember {
    user_id: string;
    email: string;
    display_name: string;
    role: string;
    status: string;
    mfa_enabled: boolean;
}

export interface ApprovalRecord {
    id: string;
    gate: string;
    status: string;
    approver: string;
    approver_role: string;
    declaration_version: string;
    rationale: string | null;
    content_manifest_hash: string;
    bound_artifacts: { id?: string; kind?: string; hash: string; name?: string }[];
    decided_at: string;
    invalidated_at: string | null;
    invalidation_reason: string | null;
    is_current: boolean;
}

export interface Provider {
    key: string;
    display_name: string;
    kind: string;
    enabled: boolean;
    gate_status: string;
    gate_notes: string | null;
    docs_url: string | null;
    terms_url: string | null;
    attribution: string | null;
    capabilities: Record<string, { supported?: boolean; note?: string }>;
    requires_user_connection: boolean;
    terms_reviewed_at: string | null;
}

// ---------------------------------------------------------------------------------------------- M2 discovery

export interface ResearchProfileData {
    topics: string[];
    methods: string[];
    geography: string[];
    travel_budget: number | null;
    currency: string;
    desired_venues: string[];
    lead_time_weeks: number | null;
    preferred_publishers: string[];
    excluded_venues: string[];
}

export interface ScoreComponent {
    name: string;
    score: number | null;
    uncertainty: string;
    evidence: string[];
}

export interface CandidateDeadline {
    kind: string;
    date: string | null;
    timezone: string | null;
    due_at: string | null;
    problems: string[];
}

export interface Candidate {
    id: string;
    rank: number;
    name: string;
    acronym: string | null;
    year: number | null;
    official_url: string;
    tracks: string[];
    deadlines: CandidateDeadline[];
    location: string | null;
    publisher: string | null;
    total_score: number;
    components: ScoreComponent[];
    excluded: boolean;
    exclusion_reason: string | null;
    questionable_evidence: { source_url?: string; note?: string }[];
    status: string;
    snapshot_hash: string | null;
    note: string;
}

export interface MonitorCheck {
    id: string;
    url: string;
    outcome: "not_modified" | "unchanged" | "changed" | "failed" | string;
    detail: string | null;
    snapshot_id: string | null;
    at: string;
}

export interface RegistryEntry {
    id: string;
    series_key: string;
    name: string;
    acronym: string | null;
    publisher: string | null;
    homepage_url: string;
    cfp_urls: string[];
    verification_status: string;
    verified_by: string | null;
    verified_at: string | null;
    questionable_evidence: { source_url?: string; note?: string }[];
    keywords: string[];
}

// ---------------------------------------------------------------------------------------------- M3 templates

export interface TemplateFileEntry {
    path: string;
    sha256: string;
    size: number;
    role: string;
    protected: boolean;
}

export interface CompileCheck {
    id: string;
    status: string;
    detail: string;
}

export interface CompileRunEntry {
    id: string;
    kind: string;
    options: { mode?: string; anonymous?: boolean; bib_mode?: string };
    status: string;
    pages: number | null;
    checks: CompileCheck[];
    errors: string[];
    freshness: string;
    created_at: string;
    pdf_artifact_id: string | null;
    report_artifact_id: string | null;
    log_artifact_id: string | null;
    source_bundle_artifact_id: string | null;
    manuscript_version_id: string | null;
}

export interface TemplateEntry {
    id: string;
    mode: "submission" | "camera_ready" | string;
    origin: "official_link" | "researcher_supplied" | string;
    source_url: string | null;
    declared_origin: string | null;
    license_note: string | null;
    overleaf_export_allowed: boolean | null;
    archive_hash: string | null;
    archive_artifact_id: string | null;
    family: string | null;
    class_name: string | null;
    bib_modes: string[];
    bibtex_style: string | null;
    requires_generation: boolean;
    status: string;
    supported: boolean;
    issues: { severity: string; code: string; message: string; path?: string | null }[];
    unsupported_reasons: string[];
    cfp_consistency: { status?: string; detail?: string; cfp_value?: string | null; template_family?: string | null; quote?: string | null };
    retrieved_at: string | null;
    confirmed_at: string | null;
    label: "submission_ready_capable" | "not_submission_ready" | string;
    files: TemplateFileEntry[];
    compile_runs: CompileRunEntry[];
    declaration: string;
}

// ---------------------------------------------------------------------------------------------- M4 literature

export interface LiteratureSetup {
    message: string;
    enabled_sources: { key: string; name: string; attribution: string | null }[];
    optional_connections: { key: string; name: string; gate_status: string }[];
}

export interface ProviderRunStatus {
    status: string;
    total_reported?: number | null;
    retrieved?: number;
    error?: string | null;
    reason?: string | null;
    notes?: string[];
}

export interface SearchRunEntry {
    id: string;
    query: string;
    filters: { year_from?: number | null; year_to?: number | null; max_results?: number };
    providers: string[];
    provider_status: Record<string, ProviderRunStatus>;
    status: string;
    executed_at: string | null;
    retrieved_count: number;
    purpose: string;
    created_at: string;
    record_artifact_id: string | null;
}

export interface PaperRights {
    storage_permitted?: boolean;
    model_use_permitted?: boolean;
    redistribution_permitted?: boolean;
    basis?: string;
    statement?: string;
}

export interface IdentityVerification {
    record?: { title?: string; authors?: string[]; year?: number | null; venue?: string | null };
    source?: string;
    basis?: string;
    reason?: string;
    title_similarity?: number;
    title_coverage?: number;
    year_match?: boolean;
    outcome?: string;
    error?: string;
    checked_at?: string;
    verifier?: string;
    fulltext_detail?: string | null;
}

export interface PaperEntry {
    id: string;
    doi: string | null;
    title: string;
    authors: string[];
    year: number | null;
    venue: string | null;
    abstract: string | null;
    abstract_rights: string;
    license: string | null;
    open_access: boolean | null;
    fulltext_status: string;
    fulltext_locations: { url: string; license?: string | null; access?: string | null; source?: string }[];
    rights: PaperRights;
    identity_status: string;
    identity_verification: IdentityVerification;
    sources: string[];
    origin: string;
    notes: string | null;
    retracted: boolean;
    global_paper_id: string | null;
    fulltext_artifact_id: string | null;
    screening: { stage: string; decision: string; reason: string; method: string; at: string }[];
}

export interface PassageEntry {
    id: string;
    paper_id: string;
    quote: string;
    role: string;
    summary: string | null;
    locator: { char_start?: number | null; char_end?: number | null; page?: number | null; section?: string | null };
    source_kind: string;
    verified_in_source: boolean;
    extraction_method: string;
    extracted_by: string;
    freshness: string;
}

export interface ClaimDecisionSummary {
    status: string;
    policy_version: string;
    rule_id: string;
    satisfied: string[];
    outstanding: string[];
    human_required: boolean;
    outstanding_descriptions?: string[];
}

export interface VerificationEntry {
    id: string;
    check: string;
    outcome: string;
    method: string;
    verifier: string;
    verifier_version: string;
    evidence: Record<string, unknown>;
    uncertainty: string | null;
    requires_human_confirmation: boolean;
    at: string;
    is_current: boolean;
}

export interface ClaimEntry {
    id: string;
    claim_key: string;
    proposition: string;
    normalized: Record<string, string | null>;
    kind: string;
    category: string;
    critical: boolean;
    status: string;
    gate_eligible: boolean;
    decision: Partial<ClaimDecisionSummary>;
    origin: string;
    version: number;
    supersedes_id: string | null;
    supports: { id: string; passage_id: string | null; paper_id: string | null; relation: string; result_ref: string | null; is_current: boolean }[];
    verifications: VerificationEntry[];
    decisions: (ClaimDecisionSummary & { state: string; at: string })[];
}

export interface EvidenceGraph {
    passages: PassageEntry[];
    claims: ClaimEntry[];
    policy: { version: string; requirements: Record<string, string> };
    labels: Record<string, string>;
}

export interface CoverageAssessment {
    version: number;
    artifact_id: string;
    counts: {
        sources_queried: string[];
        unavailable_sources: string[];
        queries: { query: string; filters: Record<string, unknown>; executed_at: string | null; providers: Record<string, ProviderRunStatus> }[];
        retrieved_records: number;
        unique_records: number;
        papers_total: number;
        manual_or_uploaded: number;
        fulltext_reviewed: number;
        abstract_only: number;
        metadata_only: number;
        fulltext_inaccessible_or_not_permitted: number;
        screened: number;
        included: number;
        excluded: number;
        exclusion_reasons: string[];
        papers_contributing_verified_evidence: number;
        identity_verified: number;
        identity_problems: number;
    };
    coverage_level: string;
    rationale: string;
    limitations: string[];
    message: string;
}

// ---------------------------------------------------------------------------------------------- M4 opportunities

export interface RationaleEntry {
    id: string;
    version: number;
    problem: string;
    gap: string;
    gap_evidence: { passage_id: string; quote: string; paper_id: string }[];
    importance_to_venue: string;
    research_question: string;
    intended_contribution: string;
    success_criterion: string;
    status: string;
    artifact_id: string | null;
    label: string;
}

export interface StudyTypeRec {
    id: string;
    study_type: string;
    venue_category: string;
    fit_rationale: string;
    track_accepts: string;
    track_rule_ref: Record<string, unknown>;
    required_inputs: string[];
    reporting_standard: string | null;
    blockers: string[];
    method_enabled: boolean;
    method_availability: string;
    advisory: boolean;
}

export interface FeasibilityEntry {
    id: string;
    version: number;
    deadlines: { kind: string; due_at: string | null; stated_timezone: string | null; status: string }[];
    estimates: { research_weeks?: number[]; writing_weeks?: number; validation_weeks?: number; source?: string };
    cost_estimate: { platform_budget_remaining_cents?: number; currency?: string; note?: string };
    constraints: string[];
    assumptions: string[];
    status: string;
    uncertainty: string;
    slack_days: number | null;
    note: string;
}

export interface OpportunityEntry {
    id: string;
    position: number;
    title: string;
    research_question: string;
    details: {
        cfp_alignment?: string | null;
        potential_contribution?: string | null;
        how_it_differs?: string | null;
        boundary_conditions?: string | null;
        data_availability?: string | null;
        compute_estimate?: string | null;
        ethics_constraints?: string | null;
        threats_to_novelty?: string[] | null;
    };
    closest_work: { paper_id: string; title: string; year: number | null; doi: string | null; identity_status: string }[];
    novelty_caveat: string;
    status: string;
    provenance: { provider?: string; model?: string; label?: string; prompt_version?: string };
    rationale: RationaleEntry | null;
    study_types: StudyTypeRec[];
    feasibility: FeasibilityEntry | null;
}

export interface OpportunityList {
    direction_state: "direction_proposed" | "awaiting_H1" | string;
    items: OpportunityEntry[];
    note: string;
}

export interface StudyTypeTaxonomy {
    taxonomy: {
        study_type: string;
        title: string;
        definition: string;
        enabled_for_submission_ready: boolean;
        availability: string;
        planning_only_reason: string | null;
        reporting_standard: string | null;
        definition_version: number;
    }[];
    venue_categories: Record<string, string>;
    recommendations: StudyTypeRec[];
    note: string;
}

// ---------------------------------------------------------------------------------------------- M5 method & contribution

export interface MethodInstance {
    id: string;
    definition_key: string;
    study_type: string;
    title: string;
    definition_version: number;
    venue_category: string;
    enabled_for_submission_ready: boolean;
    availability: string;
    planning_only_reason: string | null;
    status: string;
    track_accepts: string;
    selection_rationale: string | null;
    override_of_recommendation: boolean;
    reuse_decisions: { item: string; decision: string; reason: string }[];
    frozen_at: string | null;
    created_at: string;
    switch_effects?: { stale_artifact_ids?: string[]; invalidated_approvals?: { gate: string }[]; effects?: string[]; reopened_to?: string | null };
}

export interface StageDefinitionEntry {
    id: string;
    title: string;
    description: string;
    predecessor_stage_ids: string[];
    input_artifact_kinds: string[];
    output_artifact_kinds: string[];
    validator_ids: string[];
    waits_for_human: boolean;
    automation: string;
    required: boolean;
    status: string;
    output_artifact_id: string | null;
    validator_results: { id: string; passed: boolean; detail: string }[];
}

export interface WorkflowDefinitionView {
    instance: MethodInstance | null;
    definition: {
        id: string;
        title: string;
        plain_definition: string;
        protocol_sections: string[];
        reporting_standard: string | null;
        enabled_for_submission_ready: boolean;
        planning_only_reason: string | null;
    } | null;
    stages: StageDefinitionEntry[];
    frozen_protocol_version?: number | null;
}

export interface InstitutionalApproval {
    required: boolean;
    status: "obtained" | "pending" | "not_required" | "not_applicable";
    body?: string | null;
    reference?: string | null;
    document_artifact_id?: string | null;
}

export interface EthicsRights {
    involves_human_participants: boolean;
    personal_data: boolean;
    sensitive_data: boolean;
    restricted_datasets: boolean;
    data_licences: string[];
    third_party_rights_notes?: string | null;
    institutional_approval: InstitutionalApproval;
    consent_procedure?: string | null;
    deidentification_plan?: string | null;
    declaration_text_accepted: boolean;
}

export interface ReviewIssue {
    severity: "blocker" | "major" | "minor" | "suggestion" | string;
    section: string;
    issue: string;
    rationale: string;
    proposed_fix: string;
    resolved?: string;
    resolution_note?: string;
}

export interface ProtocolValidation {
    missing_sections: string[];
    ethics_blockers: string[];
    cost_flags: string[];
    review: string[];
    unresolved_blocker_issues: ReviewIssue[];
    ready_for_h2: boolean;
}

export interface ProtocolEntry {
    id: string;
    version: number;
    status: "draft" | "frozen" | "superseded" | string;
    sections: Record<string, string>;
    ethics_rights: EthicsRights | null;
    compute_estimate: string | null;
    cost_estimate_cents: number | null;
    artifact_id: string;
    content_hash: string;
    is_amendment: boolean;
    amendment_rationale: string | null;
    after_data_inspection: boolean;
    frozen_at: string | null;
    review_status: string | null;
    review_issues: ReviewIssue[];
    review_waiver_rationale: string | null;
    created_at: string;
    validation: ProtocolValidation | null;
    ethics_declaration_text: string;
}

export interface ProtocolList {
    items: ProtocolEntry[];
    required_sections: string[];
    declaration?: string;
}

export interface ContributionEntry {
    id: string;
    user_id: string;
    type: string;
    workspace_field: string | null;
    title: string;
    text: string | null;
    artifact_id: string | null;
    content_hash: string;
    license: string | null;
    visibility: string;
    pii_classification: string;
    rights_statement: string | null;
    relation_to_protocol: string | null;
    scan_report: Record<string, unknown>;
    created_at: string;
}

export interface MetricValue {
    name: string;
    value: number;
    unit: string | null;
    n?: number | null;
    condition?: string | null;
    ci_low?: number | null;
    ci_high?: number | null;
    numerator?: number | null;
    denominator?: number | null;
}

export interface ResultAssessment {
    id: string;
    assurance_level: string;
    checks: { id?: string; check?: string; status?: string; passed?: boolean; detail?: string }[];
    missing: string[];
    impossible_checks: string[];
    wording_limits: string[];
    blockers: string[];
    assessor: string;
    reviewer_note: string | null;
    artifact_id: string;
}

export interface ResultEntry {
    id: string;
    result_key: string;
    title: string;
    manifest: {
        protocol_version: number;
        protocol_hash: string;
        metrics: MetricValue[];
        files: { role: string; artifact_id: string; description?: string | null }[];
        data_origin: string;
        limitations: string;
        sample_size?: number | null;
        synthetic_or_simulated?: boolean;
        run_type?: string;
        [k: string]: unknown;
    };
    artifact_id: string;
    origin: string;
    status: string;
    assurance_level: string;
    is_current: boolean;
    created_at: string;
    assessment: ResultAssessment | null;
}

export interface MatrixRowEntry {
    id?: string;
    rq_index: number;
    research_question: string;
    intended_novelty: string;
    intended_contribution: string;
    success_criterion: string;
    evidence_ids: string[];
    validity_assessment: string | null;
    outcome: "supported" | "partially_supported" | "not_supported" | "inconclusive" | null;
    limitations: string | null;
    h3_decision: "accepted" | "revise" | null;
    origin?: "draft" | "researcher_reviewed" | string;
    version?: number;
    reviewed_at?: string | null;
}

export interface MatrixView {
    items: MatrixRowEntry[];
    outcomes?: string[];
    gap_resolution?: { status: string; supporting_ids: string[]; explanation: string; at: string } | null;
    note: string;
}

export interface Declaration {
    version: string | number;
    text: string;
    approver: string;
}

export interface ApprovalsView {
    declarations: Record<string, Declaration>;
    items: ApprovalRecord[];
}

// ---------------------------------------------------------------------------------------------- M6 manuscript

export type SpanKind = "prior_work" | "observed_result" | "method" | "interpretation" | "hypothesis" | "limitation" | "contribution_statement" | "framing";

export interface SpanIssue {
    code: string;
    severity: "blocker" | "major" | "minor" | string;
    message: string;
}

/** A table issue. Tables have no span ID, so they are located by section key, index and caption. */
export interface TableIssue extends SpanIssue {
    section: string;
    table_index: number;
    caption: string;
}

export interface ContentSpan {
    span_id: string;
    text: string;
    kind: SpanKind;
    claim_ids: string[];
    result_keys: string[];
    origin: "ai" | "human";
    protected: boolean;
}

export interface ContentSection {
    key: string;
    heading: string;
    paragraphs: { spans: ContentSpan[] }[];
    tables: { caption: string; result_keys: string[] }[];
    figures: { caption: string; artifact_id: string; file_name: string }[];
}

export interface ManuscriptContent {
    title: string;
    mode: "paper" | "proposal";
    sections: ContentSection[];
    keywords: string[];
    acknowledgments: string | null;
}

export interface SpanRecord {
    span_id: string;
    section: string;
    kind: SpanKind;
    text: string;
    claim_ids: string[];
    result_keys: string[];
    origin: "ai" | "human";
    protected: boolean;
    status: "ok" | "issues" | "stale" | string;
    issues: SpanIssue[];
}

export interface ManuscriptVersion {
    id: string;
    version: number;
    origin: "initial" | "human_edit" | "candidate_applied" | "merge" | string;
    content_hash: string;
    artifact_id: string;
    change_summary: string | null;
    created_by: string;
    created_at: string;
    checks: { spans?: number; spans_with_issues?: number; unresolved_claims?: number; blockers?: number; abstract_words?: number; table_issues?: TableIssue[] };
    content: ManuscriptContent | null;
    spans: SpanRecord[];
}

export interface GenerationCandidate {
    id: string;
    status: "pending" | "ready" | "stale" | "applied" | "merged" | "rejected" | "failed" | string;
    base_version_id: string;
    sections: string[];
    rationale: Record<string, unknown>;
    conflicts: { section?: string; kept_protected_spans?: string[]; note?: string; error?: string }[];
    provenance: { sections?: { section: string; provider?: string; model?: string; label?: string; prompt_version?: string }[] };
    created_at: string;
    artifact_id: string | null;
    task_id: string;
}

export interface SectionDiff {
    section: string;
    diff: string;
}

export interface CandidateDetail extends GenerationCandidate {
    content: ManuscriptContent;
    diff_vs_current: SectionDiff[];
    is_stale: boolean;
}

export interface ManuscriptView {
    manuscript: null | {
        id: string;
        title: string;
        study_type: string | null;
        current_version: ManuscriptVersion;
    };
    unresolved_claim_queue?: { span_id: string; section: string; text: string }[];
    gap_argument_sections_present?: Record<string, boolean>;
    bibliography?: { cite_key: string; paper_id: string; bibtex: string }[];
    candidates?: GenerationCandidate[];
}

// --------------------------------------------------------------------------- M7 review, compliance, integrity
// Hand-written from apps/api/src/rp_api/features/review.py (the API declares no response models; gap #1).
export type ReviewFunction = "scientific" | "citation_evidence" | "technical" | "compliance";
export type FindingSeverity = "blocker" | "major" | "minor" | "suggestion";
export type FindingStatus = "open" | "fixed" | "accepted_risk" | "rejected_with_reason";
export type CheckStatus = "passed" | "failed" | "manual_check" | "not_performed" | "warning";

export interface ReviewReportSummary {
    function: ReviewFunction;
    status: "performed" | "partial" | "not_performed";
    artifact_id: string;
    frozen_at: string;
    summary: Record<string, unknown> & { reason?: string; checks?: ComplianceCheck[] };
    provenance: Record<string, unknown>;
}

export interface ReviewFinding {
    id: string;
    function: ReviewFunction;
    severity: FindingSeverity;
    category: string;
    title: string;
    rationale: string;
    check: string;
    proposed_fix: string | null;
    span_ids: string[];
    claim_ids: string[];
    artifact_ids: string[];
    rule_ids: string[];
    status: FindingStatus;
    resolution_note: string | null;
    resolved_by: string | null;
    resolved_at: string | null;
    resolved_in_version: number | null;
}

export interface SpanMeaning {
    span_id: string;
    verdict: "faithful" | "scope_drift" | "strength_overstated" | "unsupported" | "contradicted" | "not_performed";
    rationale: string;
    suggested_wording: string | null;
}

export interface ClaimCheck {
    claim_key: string;
    critical: boolean;
    selection: "critical" | "sampled";
    source_status: string;
    source_detail: string;
    meaning: SpanMeaning[];
    method: string;
    reused: boolean;
}

export interface ComplianceCheck {
    id: string;
    status: CheckStatus;
    detail: string;
    blocking: boolean;
    rule_id: string | null;
    quote: string | null;
    source: string | null;
}

export interface MetaReview {
    counts: Record<string, Record<FindingSeverity, number>>;
    disagreements: { span_id?: string; claim_id?: string; flagged_by: string[]; judged_ok_by: string }[];
    not_performed: { function: string; detail: string | null }[];
    note: string;
}

export interface ReviewRound {
    id: string;
    manuscript_version: number;
    manuscript_version_id: string;
    status: "running" | "complete" | "failed";
    functions: ReviewFunction[];
    task_id: string;
    created_at: string;
    meta: MetaReview | null;
    meta_artifact_id: string | null;
    reports: ReviewReportSummary[];
    findings?: ReviewFinding[];
    claim_checks?: ClaimCheck[];
    compliance_decisions?: { check_id: string; decision: string; rationale: string; decided_by: string; at: string }[];
}

export interface ReviewsView {
    items: ReviewRound[];
    current_version_id: string | null;
    revision_cycles: { used: number; limit: number };
    sampling_rule: { id: string; description: string };
    decision_declaration: string;
}

export interface IntegrityCheckEntry {
    id: string;
    title: string;
    status: CheckStatus;
    detail: string;
    evidence: Record<string, unknown>;
    scope: string;
    limitations: string | null;
    blocking: boolean;
    requires_decision: boolean;
    decision: null | { decision: string; rationale: string; decided_by: string; at: string };
}

export interface IntegrityReportEntry {
    id: string;
    status: "running" | "complete";
    manuscript_version: number;
    engine: string;
    artifact_id: string | null;
    created_at: string;
    checks: IntegrityCheckEntry[];
    summary: { failed: string[]; awaiting_decision: string[]; passed: boolean; engine: string; disclaimer: string };
}

export interface IntegrityView {
    items: IntegrityReportEntry[];
    decision_declaration: string;
}

// ---------------------------------------------------------------------------------------------------- M8 submission
export interface AuthorAssentRecord {
    method: "in_product" | "offline_attestation";
    at: string;
    evidence: string | null;
    recorded_by: string;
}

export interface AuthorEntry {
    id: string;
    position: number;
    name: string;
    email: string | null;
    affiliations: string[];
    orcid: string | null;
    user_id: string | null;
    corresponding: boolean;
    contribution_roles: string[];
    contribution_statement: string;
    competing_interests: string;
    funding: string;
    record_version: number;
    assent: AuthorAssentRecord | null;
}

export interface AuthorsView {
    record_version: number;
    authors: AuthorEntry[];
    manuscript_version: number | null;
    author_approval_text: string;
    offline_attestation_text: string;
    note: string;
}

/** Request body for one author (mirrors rp_contracts.submission.AuthorIn). */
export interface AuthorInput {
    name: string;
    email: string | null;
    affiliations: string[];
    orcid: string | null;
    user_id: string | null;
    corresponding: boolean;
    contribution_roles: string[];
    contribution_statement: string;
    competing_interests: string;
    funding: string;
    human_confirmed: boolean;
}

export interface Disclosures {
    competing_interests: string;
    funding: string;
    ethics_statement: string;
    ai_use: string;
    ai_policy_text: string;
    ai_policy_source: string;
    ai_policy_interpretation: string;
    data_availability: string | null;
}

export interface DisclosuresView {
    disclosures: Disclosures | null;
    record_version: number;
    venue_ai_policy_from_cfp: { quote: string | null; rule_id: string; status: string } | null;
    ai_drafted_spans: number;
    guidance: string;
}

export interface DeadlineRow {
    id: string;
    kind: string;
    due_at: string | null;
    timezone: string | null;
    mandatory: boolean | null;
    note?: string;
}

export interface EligibilityResult {
    id?: string;
    action: string;
    status: "eligible" | "ineligible" | "needs_human_resolution";
    evaluated_at: string;
    governing: DeadlineRow[];
    context: DeadlineRow[];
    pending_prerequisites: DeadlineRow[];
    reasons: string[];
    evaluator: string;
}

export interface ReadinessCheck {
    gate: string;
    passed: boolean;
    reasons: string[];
}

export interface ReadinessAssessmentEntry {
    id: string;
    stage: string;
    checks: ReadinessCheck[];
    manual_checks: { id: string; detail: string; source: string | null }[];
    limitations: string[];
    source_hashes: Record<string, string>;
    artifact_id: string;
    assessor: string;
    assessor_version: string;
    created_at: string;
}

export interface ReadinessView {
    current_stage: string;
    gates: Record<string, GateResult>;
    items: ReadinessAssessmentEntry[];
    notice: string;
}

export interface ContentItem {
    role: string;
    path: string;
    artifact_id: string;
    kind: string;
    sha256: string;
    media_type: string;
}

export interface ContentManifestView {
    items: ContentItem[];
    problems: string[];
    manuscript_version: number;
    authors_without_approval: string[];
    declaration: string;
}

export interface FinalApprovalResult {
    approval_id: string;
    content_manifest_artifact_id: string;
    content_manifest_hash: string;
    transition: TransitionResult;
}

export interface ExportPackageEntry {
    id: string;
    status: "building" | "built" | "verified" | "failed";
    approved: boolean;
    label: "approved" | "unapproved";
    artifact_id: string | null;
    checksum: string | null;
    content_manifest_hash: string | null;
    problems: string[];
    verified_at: string | null;
    created_at: string;
    name: string | null;
    stale: string | null;
    files: { path: string; sha256: string }[];
}

export interface PackagesView {
    items: ExportPackageEntry[];
    notice: string;
}

// --------------------------------------------------------------------------- M9 platform-executed experiments
export type DataNature = "empirical" | "synthetic" | "simulated";
export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "timed_out" | "sandbox_unavailable" | "cancelled";

export interface PlanInputSpec {
    artifact_id: string;
    path: string;
    data_nature: DataNature;
}

export interface ExperimentPlanSpec {
    title: string;
    code_artifact_id: string;
    code_path: string;
    entrypoint: string[];
    inputs: PlanInputSpec[];
    image: string;
    seed: number;
    limits: { cpus: number; memory_mb: number; timeout_s: number };
    run_type: "exploratory" | "confirmatory";
    metrics: { name: string; condition?: string | null }[];
    tolerance: number;
    predictions_path: string;
    metrics_path: string;
    sample_size: number | null;
    data_origin: string;
    data_rights: string;
    limitations: string;
}

export interface RecomputationCheck {
    id: string;
    status: string;
    detail: string;
    evidence?: Record<string, unknown>;
}

export interface Recomputation {
    status: "passed" | "failed" | "not_performed";
    detail?: string;
    validator: string;
    reported?: Record<string, number>;
    checks: RecomputationCheck[];
}

export interface ReproductionRow {
    metric: string;
    first: number | null;
    rerun: number | null;
    difference: number | null;
    within_tolerance: boolean;
}

export interface Reproduction {
    tolerance: number;
    rows: ReproductionRow[];
    match: boolean;
}

export interface ExperimentRunEntry {
    id: string;
    status: RunStatus;
    rerun_of: string | null;
    task_id: string;
    exit_code: number | null;
    duration_s: number | null;
    reported_metrics: Record<string, number> | null;
    recomputation: Recomputation | null;
    reproduction: Reproduction | null;
    failure_reason: string | null;
    run_manifest_artifact_id: string | null;
    raw_output_artifact_id: string | null;
    predictions_artifact_id: string | null;
    log_artifact_id: string | null;
    recomputation_artifact_id: string | null;
    result_manifest_id: string | null;
    created_at: string;
    promotable: boolean;
}

export interface ExperimentPlanEntry {
    id: string;
    plan_number: number;
    title: string;
    status: "draft" | "approved" | "superseded";
    run_type: "exploratory" | "confirmatory";
    synthetic: boolean;
    image_ref: string;
    code_hash: string;
    input_hashes: Record<string, string>;
    protocol_hash: string;
    estimate_cents: number;
    spec: ExperimentPlanSpec;
    artifact_id: string;
    approved_at: string | null;
    rerun_command: string;
    declaration: string;
    runs: ExperimentRunEntry[];
}

export interface ExperimentsView {
    items: ExperimentPlanEntry[];
    images: string[];
    plan_declaration: string;
}

export interface PromoteResult {
    result_key: string;
    result_id: string;
    task: Task;
    rerun_documented: boolean;
}

// --------------------------------------------------------------------------- M10 evidence synthesis / qualitative
export type ReviewType = "systematic_review" | "meta_analysis" | "mapping_review" | "scoping_review" | "tertiary_review";
export type SynthesisKind = "narrative" | "meta_analysis" | "map" | "review_of_reviews";

export interface ReviewSearchSpec {
    provider: string;
    query: string;
    year_from: number | null;
    year_to: number | null;
    max_results: number;
}

export interface ReviewSpec {
    review_type: ReviewType;
    question: string;
    searches: ReviewSearchSpec[];
    inclusion_criteria: string[];
    exclusion_reasons: string[];
    extraction_form: { key: string; label: string; required: boolean }[];
    appraisal_tool: string | null;
    appraisal_items: { key: string; label: string; ratings: string[] }[];
    synthesis: SynthesisKind;
    effect_measure: string | null;
    pooling_model: "fixed" | "random_dl" | null;
    charting_scheme: { key: string; label: string; categories: string[] }[];
    reporting_standard: string;
}

export interface ReviewFlow {
    identified: number;
    duplicates_removed: number;
    screened: number;
    screened_out: number;
    awaiting_screening: number;
    full_text_assessed: number;
    awaiting_full_text: number;
    excluded_full_text: number;
    excluded_full_text_reasons: Record<string, number>;
    included: number;
    included_ids: string[];
}

export interface ScreeningState {
    decision: "include" | "exclude";
    reason: string | null;
    method: string;
    by: string;
}

export interface ReviewRecord {
    paper_id: string;
    title: string | null;
    doi: string | null;
    title_abstract: ScreeningState | null;
    full_text: ScreeningState | null;
    extracted: boolean;
}

export interface MetaAnalysisResult {
    status: "computed" | "not_performed";
    detail?: string;
    model?: string;
    k?: number;
    estimate?: number;
    se?: number;
    ci_low?: number;
    ci_high?: number;
    q?: number;
    df?: number;
    tau2?: number;
    i2?: number;
    engine?: string;
    effect_measure?: string | null;
}

export interface MapResult {
    dimensions: Record<string, Record<string, number>>;
    studies: number;
    problems: string[];
    engine: string;
}

export interface OverlapResult {
    status: "computed" | "not_performed";
    detail?: string;
    reviews?: number;
    primary_studies?: number;
    inclusions?: number;
    cca?: number;
    level?: string;
    engine?: string;
}

export interface StoredSynthesis<T = unknown> {
    result: T;
    inputs_hash: string;
    artifact_id: string;
}

export interface ReviewWorkspaceView {
    specification: ReviewSpec;
    protocol_hash: string;
    flow: ReviewFlow;
    searches: { id: string; query: string; providers: string[]; status: string; executed_at: string | null; retrieved: number | null; filters: Record<string, unknown> }[];
    records: ReviewRecord[];
    syntheses: Partial<Record<"flow" | "meta_analysis" | "map" | "overlap", StoredSynthesis>>;
    current_inputs_hash: string;
}

export interface ReviewAppendix {
    artifact_id: string;
    reporting_standard: string;
    protocol: { version: number; hash: string };
    searches: { provider: string[]; query: string; filters: Record<string, unknown>; executed_at: string | null; status: string; retrieved: number | null }[];
    flow: ReviewFlow;
}

export interface QualCodeEntry {
    id: string;
    code: string;
    definition: string;
    segments: number;
}

export interface QualSegmentEntry {
    id: string;
    code_id: string;
    contribution_id: string;
    quote: string;
    verified: boolean;
    memo: string | null;
}

export interface QualThemeEntry {
    id: string;
    name: string;
    description: string;
    code_ids: string[];
    interpretation: string;
}

export interface QualWorkspace {
    codes: QualCodeEntry[];
    segments: QualSegmentEntry[];
    themes: QualThemeEntry[];
}

// ---------------------------------------------------------------- AI provider choice (model_settings)
export interface AnthropicConnection {
    connected: boolean;
    key_hint?: string | null;
    connected_at?: string | null;
    status?: string;
    consent_text: string;
}

export interface ModelConnections {
    anthropic: AnthropicConnection;
    environment: string;
}

export type ModelProviderKey = "claude_cli" | "anthropic" | "fixture";

export interface ModelProviderOption {
    key: ModelProviderKey;
    label: string;
    available: boolean;
    reason: string | null;
    data_flow_attested: boolean;
}

export interface ModelProviderView {
    selected: ModelProviderKey | null;
    options: ModelProviderOption[];
    can_change: boolean;
    note: string;
}
