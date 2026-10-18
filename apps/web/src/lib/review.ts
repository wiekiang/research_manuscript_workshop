/**
 * M7 review helpers. Review is diagnostic (spec §2.11): the UI never shows a score or an acceptance prediction, and a
 * check that did not run is shown as "not performed", never as passed.
 */
import type { ApiError } from "@/lib/api/client";
import type { CheckStatus, FindingSeverity, ReviewFinding, ReviewFunction, ReviewReportSummary } from "@/lib/api/types";

export const FUNCTION_ORDER: ReviewFunction[] = ["scientific", "citation_evidence", "technical", "compliance"];

export const FUNCTION_LABEL: Record<string, string> = {
    scientific: "Scientific and methodological review",
    citation_evidence: "Citation and evidence review",
    technical: "Technical recomputation",
    compliance: "Venue-compliance review",
};

export const FUNCTION_METHOD: Record<string, string> = {
    scientific: "Model-assisted reviewer that sees the manuscript, approved protocol, H3 matrix and claims/results only.",
    citation_evidence: "Opens the stored source for every critical claim (and a documented sample of others) deterministically; a model-assisted check compares each linked sentence with the opened evidence.",
    technical: "Deterministic recomputation of reported metrics from the supplied raw outputs.",
    compliance: "Deterministic reading of the official CFP snapshot rules, the confirmed template and the compile run of the same version.",
};

export const SEVERITY_ORDER: FindingSeverity[] = ["blocker", "major", "minor", "suggestion"];
export const SEVERITY_LABEL: Record<FindingSeverity, string> = { blocker: "Blocker", major: "Major", minor: "Minor", suggestion: "Suggestion" };

export const RESOLUTION_LABEL: Record<string, string> = {
    open: "Open",
    fixed: "Fixed (re-checked by the next review)",
    accepted_risk: "Accepted risk",
    rejected_with_reason: "Rejected with reason",
};

export const VERDICT_LABEL: Record<string, string> = {
    faithful: "Faithful",
    scope_drift: "Scope drift",
    strength_overstated: "Overstated strength",
    unsupported: "Unsupported",
    contradicted: "Contradicted",
    not_performed: "Not performed",
};

/** Report status → badge key. "not_performed" deliberately maps to its own key so it can never read as passed. */
export function reportStatusKey(status: ReviewReportSummary["status"] | string): string {
    if (status === "performed") return "report_performed";
    if (status === "partial") return "report_partial";
    return "not_performed";
}

export function checkStatusKey(status: CheckStatus | string): string {
    return ["passed", "failed", "manual_check", "not_performed", "warning"].includes(status) ? status : "manual_check";
}

/** Findings grouped by function (fixed order) then severity (most severe first). Empty groups are omitted. */
export function groupFindings(findings: ReviewFinding[]): { fn: string; bySeverity: { severity: FindingSeverity; items: ReviewFinding[] }[] }[] {
    const fns = [...FUNCTION_ORDER, ...new Set(findings.map((f) => f.function).filter((f) => !FUNCTION_ORDER.includes(f)))];
    return fns
        .map((fn) => ({
            fn,
            bySeverity: SEVERITY_ORDER.map((severity) => ({ severity, items: findings.filter((f) => f.function === fn && f.severity === severity) })).filter(
                (g) => g.items.length > 0,
            ),
        }))
        .filter((g) => g.bySeverity.length > 0);
}

export function openBlocking(findings: ReviewFinding[], functions: string[] = ["scientific", "citation_evidence", "technical"]): ReviewFinding[] {
    return findings.filter((f) => f.status === "open" && (f.severity === "blocker" || f.severity === "major") && functions.includes(f.function));
}

/** Short guidance added under the server's own refusal message (which is always shown verbatim). */
export const REFUSAL_HINT: Record<string, string> = {
    no_newer_version: "Edit the manuscript first; “fixed” is confirmed by the next review round on the new version.",
    blocker_cannot_be_accepted: "A blocker must be fixed or rejected with a reason.",
    must_fix: "Missing, failed or contradicting evidence has to be fixed in the manuscript or the evidence.",
    rationale_required: "Explain the decision in your own words (at least 20 characters).",
    already_resolved: "Reload: someone already resolved this finding.",
    revision_limit_reached: "Resolve the remaining findings yourself; automatic revision has reached its limit.",
    nothing_to_revise: "No open finding points at manuscript text.",
    review_incomplete: "Wait for the review round to finish.",
    declaration_mismatch: "Accept the exact declaration text shown.",
    not_decidable: "A failed check cannot be waived; fix the underlying problem and run the checks again.",
    not_manual: "Only manual checks take a signed decision.",
    wrong_state: "This step is not available in the project's current stage.",
};

export function refusalHint(err: unknown): string | null {
    const code = (err as ApiError | undefined)?.code;
    return code ? (REFUSAL_HINT[code] ?? null) : null;
}

/** Resolution options the UI offers; the server remains authoritative and its refusals are shown verbatim. */
export function resolutionOptions(f: Pick<ReviewFinding, "severity">): { value: string; label: string }[] {
    const opts = [
        { value: "fixed", label: "Fixed in a newer version" },
        { value: "accepted_risk", label: "Accept the risk (with reason)" },
        { value: "rejected_with_reason", label: "Reject with reason" },
    ];
    return f.severity === "blocker" ? opts.filter((o) => o.value !== "accepted_risk") : opts;
}
