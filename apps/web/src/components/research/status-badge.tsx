import type { FC } from "react";
import {
    AlertTriangle,
    CheckCircle,
    Clock,
    FileX02,
    Hourglass03,
    Loading02,
    PauseCircle,
    PenTool02,
    RefreshCcw01,
    SlashCircle01,
    XCircle,
} from "@untitledui/icons";
import { BadgeWithIcon } from "@/components/base/badges/badges";
import { cx } from "@/utils/cx";

type BadgeColor = "gray" | "brand" | "error" | "warning" | "success" | "blue" | "indigo" | "orange";

interface StatusSpec {
    label: string;
    color: BadgeColor;
    icon: FC<{ className?: string }>;
    description: string;
}

/** Every status renders as text + color + icon, so meaning never depends on color alone. */
export const STATUS_SPECS: Record<string, StatusSpec> = {
    waiting_human: { label: "Waiting for you", color: "warning", icon: PenTool02, description: "A human decision is required before work continues" },
    needs_human_resolution: { label: "Needs your resolution", color: "warning", icon: PenTool02, description: "Ambiguous, conflicting or unverified; resolve it against the source" },
    blocked: { label: "Blocked", color: "error", icon: SlashCircle01, description: "Cannot advance until the listed problem is fixed" },
    stale: { label: "Stale", color: "orange", icon: RefreshCcw01, description: "An input changed; this must be rechecked" },
    complete: { label: "Complete", color: "success", icon: CheckCircle, description: "Finished" },
    succeeded: { label: "Succeeded", color: "success", icon: CheckCircle, description: "Task finished successfully" },
    validated: { label: "Cross-checked", color: "blue", icon: CheckCircle, description: "Two independent methods agree and the quote was found in the source; still subject to your confirmation" },
    extracted: { label: "Extracted", color: "gray", icon: Clock, description: "Found by one method; non-blocking" },
    confirmed: { label: "Confirmed by you", color: "success", icon: CheckCircle, description: "A researcher confirmed this against the source" },
    rejected: { label: "Rejected", color: "gray", icon: XCircle, description: "A researcher rejected this item" },
    failed: { label: "Failed", color: "error", icon: AlertTriangle, description: "The task failed; see the error" },
    failed_terminal: { label: "Failed", color: "error", icon: AlertTriangle, description: "The task failed and will not retry" },
    failed_retryable: { label: "Retrying", color: "orange", icon: RefreshCcw01, description: "The task failed and will retry" },
    running: { label: "Running", color: "brand", icon: Loading02, description: "In progress" },
    queued: { label: "Queued", color: "gray", icon: Hourglass03, description: "Waiting to start" },
    cancelled: { label: "Cancelled", color: "gray", icon: FileX02, description: "Stopped by a researcher; partial artifacts remain labelled" },
    paused: { label: "Paused", color: "gray", icon: PauseCircle, description: "Work is held until resumed" },
    valid: { label: "Valid", color: "success", icon: CheckCircle, description: "Approval is bound to current content" },
    invalidated: { label: "Invalidated", color: "orange", icon: RefreshCcw01, description: "Content it covered changed; sign again" },
    superseded: { label: "Superseded", color: "gray", icon: Clock, description: "Replaced by a later approval" },
    current: { label: "Current", color: "success", icon: CheckCircle, description: "Latest committed version" },
    not_performed: { label: "Not performed", color: "gray", icon: SlashCircle01, description: "This check did not run; it was not passed" },
    passed: { label: "Passed", color: "success", icon: CheckCircle, description: "The automated check passed; it is not a guarantee of compliance" },
    manual_check: { label: "Manual check", color: "warning", icon: PenTool02, description: "Automation cannot decide this; a human must check it" },
    warning: { label: "Warning", color: "orange", icon: AlertTriangle, description: "Not blocking, but worth reviewing" },
    analyzing: { label: "Analyzing", color: "brand", icon: Loading02, description: "Retrieval and safe archive analysis in progress" },
    unsupported: { label: "Unsupported", color: "error", icon: SlashCircle01, description: "No adapter can handle this template; it cannot be labelled submission-ready" },
    compiled: { label: "Compiled", color: "success", icon: CheckCircle, description: "The sandbox produced a PDF" },
    sandbox_unavailable: { label: "Sandbox unavailable", color: "error", icon: SlashCircle01, description: "No compile sandbox was available; nothing was compiled" },
    not_modified: { label: "Not modified", color: "gray", icon: CheckCircle, description: "The server reported no change since the last fetch" },
    unchanged: { label: "Unchanged", color: "gray", icon: CheckCircle, description: "Fetched; the content is identical to the last snapshot" },
    changed: { label: "Changed", color: "orange", icon: RefreshCcw01, description: "The official source changed; affected rules need review" },
    removed: { label: "Removed from source", color: "orange", icon: RefreshCcw01, description: "The source sentence no longer appears in the latest snapshot" },
    proposed: { label: "Proposed", color: "gray", icon: Clock, description: "A ranked candidate; nothing is imported yet" },
    imported: { label: "Imported", color: "blue", icon: CheckCircle, description: "Its official CFP was queued for import" },
    dismissed: { label: "Dismissed", color: "gray", icon: XCircle, description: "You dismissed this candidate" },
    verified: { label: "Verified source", color: "success", icon: CheckCircle, description: "A platform operator verified this official source" },
    unverified_seed: { label: "Unverified seed", color: "gray", icon: Clock, description: "Listed but not yet verified; discovery does not use it" },
    retired: { label: "Retired", color: "gray", icon: FileX02, description: "No longer used for discovery" },
    // M4 literature, evidence and claims
    identity_verified: { label: "Identity verified", color: "success", icon: CheckCircle, description: "DOI and metadata checked deterministically against the registry record; this does not mean the paper supports a claim" },
    identity_mismatch: { label: "Identity mismatch", color: "error", icon: AlertTriangle, description: "The cited metadata does not match the DOI's registry record" },
    identity_not_found: { label: "DOI not registered", color: "error", icon: XCircle, description: "The DOI is not registered with Crossref or DataCite: possible fabricated or mistyped DOI" },
    identity_unverified: { label: "Identity not verified", color: "gray", icon: Clock, description: "No deterministic identity check has completed" },
    identity_unavailable: { label: "Identity check unavailable", color: "orange", icon: RefreshCcw01, description: "The registry could not be reached; nothing was verified" },
    ft_none: { label: "No full text", color: "gray", icon: Clock, description: "Only metadata or an abstract is available" },
    ft_located: { label: "Full text located", color: "gray", icon: Clock, description: "A location is known; rights are checked before anything is stored" },
    ft_retrieved: { label: "Full text stored", color: "blue", icon: CheckCircle, description: "Stored under its recorded rights; not yet parsed" },
    ft_parsed: { label: "Full text reviewed", color: "success", icon: CheckCircle, description: "Parsed and available for verbatim passage checks" },
    ft_not_permitted: { label: "Full text not permitted", color: "warning", icon: SlashCircle01, description: "The item licence does not permit storage or model use; read it via its link" },
    ft_inaccessible: { label: "Full text inaccessible", color: "orange", icon: SlashCircle01, description: "No accessible copy could be retrieved" },
    claim_verified: { label: "Meets verification policy", color: "success", icon: CheckCircle, description: "The current evidence meets the policy minimum for this claim category; not a certification of truth" },
    claim_unverified: { label: "Not yet verified", color: "gray", icon: Clock, description: "Policy requirements are outstanding" },
    claim_contested: { label: "Contested", color: "error", icon: AlertTriangle, description: "Contradicting evidence is unresolved" },
    needs_reassessment: { label: "Needs reassessment", color: "orange", icon: RefreshCcw01, description: "Decided under a superseded policy; it cannot satisfy a current gate until reassessed" },
    migrated: { label: "Migrated", color: "blue", icon: CheckCircle, description: "Carried over after re-evaluation under the current policy" },
    feas_feasible: { label: "Feasible (advisory)", color: "success", icon: CheckCircle, description: "Advisory estimate; never a decision" },
    feas_at_risk: { label: "At risk (advisory)", color: "warning", icon: AlertTriangle, description: "Advisory estimate; you may proceed with a recorded rationale" },
    feas_infeasible: { label: "Infeasible (advisory)", color: "error", icon: AlertTriangle, description: "Advisory estimate; a model estimate alone never blocks the project" },
    direction_proposed: { label: "Direction proposed", color: "gray", icon: Clock, description: "Proposals only; no research direction has been approved" },
    awaiting_H1: { label: "Awaiting H1", color: "warning", icon: PenTool02, description: "The project waits for your research-direction decision (H1)" },
    researcher_edited: { label: "Edited by you", color: "blue", icon: PenTool02, description: "A researcher revised this version" },
    draft: { label: "Agent draft", color: "gray", icon: Clock, description: "Drafted by the agent; review and edit it" },
    partial: { label: "Partial", color: "orange", icon: AlertTriangle, description: "Some sources failed or returned partial results" },
    // M5 method, protocol, results
    method_enabled: { label: "Enabled", color: "success", icon: CheckCircle, description: "This study type can produce a submission-ready manuscript in this release" },
    method_planning_only: { label: "Planning only", color: "gray", icon: SlashCircle01, description: "This study type can be planned but cannot be labelled submission-ready in this release" },
    protocol_draft: { label: "Draft", color: "gray", icon: Clock, description: "A protocol version you can still edit; not yet frozen" },
    protocol_frozen: { label: "Frozen (H2)", color: "success", icon: CheckCircle, description: "Approved at H2; results and stages are bound to this exact hash" },
    protocol_superseded: { label: "Superseded", color: "gray", icon: Clock, description: "Replaced by a later protocol version or amendment" },
    review_requested: { label: "Review requested", color: "brand", icon: Loading02, description: "An independent methodology review is running" },
    review_performed: { label: "Review performed", color: "blue", icon: CheckCircle, description: "A model-assisted independent methodology review was recorded; it is advisory" },
    review_waived: { label: "Review waived", color: "warning", icon: PenTool02, description: "The independent review was not performed; the researcher's waiver rationale is recorded" },
    review_not_performed: { label: "Review not performed", color: "gray", icon: SlashCircle01, description: "No independent review ran (for example, no model is configured); nothing was reviewed" },
    stage_not_started: { label: "Not started", color: "gray", icon: Clock, description: "No output recorded for this stage" },
    stage_blocked_until_h2: { label: "Blocked until H2", color: "gray", icon: SlashCircle01, description: "Stages run only against the frozen (H2-approved) protocol" },
    stage_validated: { label: "Validated", color: "success", icon: CheckCircle, description: "Every deterministic validator for this stage passed" },
    // M10 evidence synthesis / qualitative
    screen_included: { label: "Included", color: "success", icon: CheckCircle, description: "A researcher included this record at this screening stage" },
    screen_excluded: { label: "Excluded", color: "gray", icon: SlashCircle01, description: "A researcher excluded this record with a protocol reason" },
    extraction_recorded: { label: "Recorded", color: "success", icon: CheckCircle, description: "An extraction and appraisal record exists for this study" },
    extraction_missing: { label: "Not yet extracted", color: "warning", icon: Clock, description: "This included study has no extraction record yet" },
    synthesis_current: { label: "Current", color: "success", icon: CheckCircle, description: "Computed from the current extraction records" },
    synthesis_stale: { label: "Stale", color: "warning", icon: RefreshCcw01, description: "Extraction records changed after this synthesis was computed; compute it again" },
    segment_verified: { label: "Verified in source", color: "success", icon: CheckCircle, description: "The quote was found verbatim in the source" },
    stage_failed: { label: "Validation failed", color: "error", icon: AlertTriangle, description: "At least one validator failed; see the details" },
    stage_stale: { label: "Stale", color: "orange", icon: RefreshCcw01, description: "The protocol changed; this output must be recorded again" },
    assurance_declared: { label: "Declared", color: "gray", icon: PenTool02, description: "Researcher attested; no independent check was possible" },
    assurance_internally_consistent: { label: "Internally consistent", color: "blue", icon: CheckCircle, description: "Deterministic consistency checks on the supplied aggregates pass; values were not recomputed" },
    assurance_independently_checked: { label: "Independently checked", color: "success", icon: CheckCircle, description: "A separate validator recomputed the metrics from supplied raw data and they match; the study itself was not re-run" },
    assurance_reproduced: { label: "Reproduced", color: "success", icon: CheckCircle, description: "A documented rerun matched preset tolerances" },
    assurance_pending: { label: "Assessment pending", color: "gray", icon: Hourglass03, description: "The assurance assessment has not finished; do not report this result yet" },
    outcome_supported: { label: "Supported", color: "success", icon: CheckCircle, description: "Your assessment: the evidence supports this research question" },
    outcome_partially_supported: { label: "Partially supported", color: "blue", icon: CheckCircle, description: "Your assessment: the evidence partly supports this research question" },
    outcome_not_supported: { label: "Not supported", color: "gray", icon: XCircle, description: "Your assessment: the evidence does not support this research question" },
    outcome_inconclusive: { label: "Inconclusive", color: "orange", icon: AlertTriangle, description: "Your assessment: the evidence cannot decide this research question" },
    // M6 manuscript
    candidate_pending: { label: "Generating", color: "brand", icon: Loading02, description: "The draft is being generated against a frozen manuscript version" },
    candidate_ready: { label: "Ready to review", color: "blue", icon: CheckCircle, description: "Generated against the current version; review the diff before applying" },
    candidate_stale: { label: "Stale candidate", color: "orange", icon: RefreshCcw01, description: "The manuscript changed while this draft was generated; it can only be merged explicitly" },
    candidate_applied: { label: "Applied", color: "success", icon: CheckCircle, description: "Applied as a new manuscript version" },
    candidate_merged: { label: "Merged", color: "success", icon: CheckCircle, description: "Selected sections were merged into a new version; human-authored text was kept" },
    candidate_rejected: { label: "Rejected", color: "gray", icon: XCircle, description: "You rejected this draft" },
    candidate_failed: { label: "Not generated", color: "error", icon: AlertTriangle, description: "The draft was not generated (for example, no model is available); nothing was invented" },
    span_ok: { label: "No issues", color: "success", icon: CheckCircle, description: "No deterministic span check reported a problem; this is not a guarantee of accuracy" },
    span_issues: { label: "Issues", color: "warning", icon: AlertTriangle, description: "Deterministic span checks reported problems" },
    span_stale: { label: "Stale", color: "orange", icon: RefreshCcw01, description: "A cited result or source changed; recheck this sentence" },
    proposal_mode: { label: "Research proposal", color: "warning", icon: PenTool02, description: "Drafted before H3: observed results cannot be reported and the manuscript cannot be completed as a paper" },
    // M7 review, compliance, integrity
    report_performed: { label: "Performed", color: "blue", icon: CheckCircle, description: "This review function ran and froze its report; findings are diagnostic, not an acceptance decision" },
    report_partial: { label: "Partially performed", color: "warning", icon: AlertTriangle, description: "Some checks of this function could not run; they are listed as not performed" },
    round_running: { label: "Reviewing", color: "brand", icon: Loading02, description: "Review functions are running independently" },
    round_complete: { label: "Complete", color: "success", icon: CheckCircle, description: "Every function froze its report and the meta-review consolidated them" },
    round_failed: { label: "Failed", color: "error", icon: AlertTriangle, description: "The review round did not finish" },
    finding_open: { label: "Open", color: "warning", icon: PenTool02, description: "Needs a researcher's resolution" },
    finding_fixed: { label: "Fixed", color: "success", icon: CheckCircle, description: "Marked fixed in a newer version; the next review round re-checks it" },
    finding_accepted_risk: { label: "Accepted risk", color: "gray", icon: PenTool02, description: "A researcher accepted this risk with a recorded reason" },
    finding_rejected_with_reason: { label: "Rejected with reason", color: "gray", icon: XCircle, description: "A researcher rejected this finding with a recorded reason" },
    verdict_faithful: { label: "Faithful", color: "success", icon: CheckCircle, description: "The sentence stays within the claim and the opened evidence" },
    verdict_scope_drift: { label: "Scope drift", color: "orange", icon: AlertTriangle, description: "Broader or different population or setting than the evidence" },
    verdict_strength_overstated: { label: "Overstated", color: "orange", icon: AlertTriangle, description: "Stronger than the evidence supports" },
    verdict_unsupported: { label: "Unsupported", color: "error", icon: XCircle, description: "The evidence does not support the sentence" },
    verdict_contradicted: { label: "Contradicted", color: "error", icon: XCircle, description: "The evidence contradicts the sentence" },
    paper_mode: { label: "Paper", color: "blue", icon: CheckCircle, description: "Drafted after H3 against approved outcomes" },
    // M8 submission preparation (the platform never submits to a venue)
    package_unapproved: { label: "UNAPPROVED", color: "warning", icon: PenTool02, description: "Built for author review only; not signed off at H4 and not a submission-ready package" },
    package_approved: { label: "Approved (H4)", color: "success", icon: CheckCircle, description: "Built from the content manifest signed at H4" },
    assent_given: { label: "Approved this version", color: "success", icon: CheckCircle, description: "The author approved this exact manuscript version in the product" },
    assent_offline: { label: "Offline attestation recorded", color: "blue", icon: PenTool02, description: "The corresponding author recorded this author's explicit approval given outside the platform, with evidence" },
    assent_missing: { label: "No approval yet", color: "warning", icon: Clock, description: "Assent is never inferred from an invitation or silence" },
    // M9 platform-executed experiments (failed runs never become results)
    plan_draft: { label: "Draft plan", color: "gray", icon: Clock, description: "Not approved; it cannot run" },
    plan_approved: { label: "Approved plan", color: "success", icon: CheckCircle, description: "The owner approved running exactly this code, inputs, image, seed and budget" },
    plan_superseded: { label: "Superseded", color: "gray", icon: Clock, description: "Replaced by another plan" },
    run_queued: { label: "Queued", color: "gray", icon: Hourglass03, description: "Waiting for the experiment sandbox" },
    run_running: { label: "Running", color: "brand", icon: Loading02, description: "Executing in the no-network sandbox" },
    run_succeeded: { label: "Run succeeded", color: "success", icon: CheckCircle, description: "The program exited normally; its metrics still need independent recomputation" },
    run_failed: { label: "Run failed", color: "error", icon: AlertTriangle, description: "The run failed; it is recorded and can never populate results" },
    run_timed_out: { label: "Timed out", color: "error", icon: AlertTriangle, description: "The run exceeded its time limit; it can never populate results" },
    run_sandbox_unavailable: { label: "Sandbox unavailable", color: "error", icon: SlashCircle01, description: "No sandbox was available (fail closed); nothing ran" },
    run_cancelled: { label: "Cancelled", color: "gray", icon: FileX02, description: "Stopped by a researcher; it can never populate results" },
    run_exploratory: { label: "Exploratory", color: "orange", icon: AlertTriangle, description: "Exploratory run: do not present it as confirmatory evidence" },
    run_confirmatory: { label: "Confirmatory", color: "blue", icon: CheckCircle, description: "Planned as confirmatory and approved before running" },
    data_empirical: { label: "Empirical data", color: "gray", icon: CheckCircle, description: "Inputs declared as empirical data" },
    data_synthetic: { label: "Synthetic data", color: "warning", icon: AlertTriangle, description: "Synthetic inputs must be labelled and cannot stand in for empirical findings" },
    data_simulated: { label: "Simulated data", color: "warning", icon: AlertTriangle, description: "Simulated inputs must be labelled and cannot stand in for empirical findings" },
    recompute_passed: { label: "Recomputed", color: "success", icon: CheckCircle, description: "A separate validator recomputed every planned metric from the stored raw outputs" },
    recompute_failed: { label: "Recomputation disagrees", color: "error", icon: XCircle, description: "The raw outputs do not reproduce the run's reported metrics; it cannot become a result" },
    recompute_not_performed: { label: "Not recomputed", color: "gray", icon: SlashCircle01, description: "No raw outputs to recompute from; this check was not passed" },
    reproduction_match: { label: "Reproduced", color: "success", icon: CheckCircle, description: "The rerun matched the first run within the preset tolerance" },
    reproduction_mismatch: { label: "Not reproduced", color: "error", icon: XCircle, description: "The rerun did not match within the preset tolerance" },
};

export function statusSpec(status: string): StatusSpec {
    return STATUS_SPECS[status] ?? { label: status.replace(/_/g, " "), color: "gray", icon: Clock, description: status };
}

export interface StatusBadgeProps {
    status: string;
    size?: "sm" | "md" | "lg";
    className?: string;
    /** Override the visible label while keeping the status semantics. */
    label?: string;
}

export function StatusBadge({ status, size = "sm", className, label }: StatusBadgeProps) {
    const spec = statusSpec(status);
    return (
        <span role="status" aria-label={`Status: ${label ?? spec.label}. ${spec.description}`} title={spec.description} className={cx("inline-flex", className)}>
            <BadgeWithIcon type="pill-color" color={spec.color} size={size} iconLeading={spec.icon}>
                {label ?? spec.label}
            </BadgeWithIcon>
        </span>
    );
}
