/**
 * M8 submission helpers (spec §2.14-2.15). The platform never submits to a venue: there is no submit action, and
 * PACKAGE_READY means the package is ready for human export through the venue's own system.
 */
import type { AuthorEntry, AuthorInput, Disclosures, ExportPackageEntry } from "@/lib/api/types";

/** Mirrors rp_contracts.submission.STAGES (exact §2.15 sequence). */
export const STAGES = [
    "research_proposal",
    "research_in_progress",
    "manuscript_draft",
    "scientific_review_complete",
    "compliance_checked",
    "approved_for_export",
    "submission_ready_package",
] as const;

export const STAGE_LABEL: Record<string, string> = {
    research_proposal: "Research proposal",
    research_in_progress: "Research in progress",
    manuscript_draft: "Manuscript draft",
    scientific_review_complete: "Scientific review complete",
    compliance_checked: "Compliance checked (pre-approval assessment)",
    approved_for_export: "Approved for export (H4)",
    submission_ready_package: "Submission-ready package",
};

/** Mirrors rp_contracts.submission.CREDIT_ROLES. */
export const CREDIT_ROLES = [
    "conceptualization",
    "data_curation",
    "formal_analysis",
    "funding_acquisition",
    "investigation",
    "methodology",
    "project_administration",
    "resources",
    "software",
    "supervision",
    "validation",
    "visualization",
    "writing_original_draft",
    "writing_review_editing",
] as const;

export const CREDIT_LABEL: Record<string, string> = {
    conceptualization: "Conceptualization",
    data_curation: "Data curation",
    formal_analysis: "Formal analysis",
    funding_acquisition: "Funding acquisition",
    investigation: "Investigation",
    methodology: "Methodology",
    project_administration: "Project administration",
    resources: "Resources",
    software: "Software",
    supervision: "Supervision",
    validation: "Validation",
    visualization: "Visualization",
    writing_original_draft: "Writing – original draft",
    writing_review_editing: "Writing – review & editing",
};

export const INTENDED_ACTIONS = [
    { value: "new_submission", label: "New manuscript submission" },
    { value: "abstract_registration", label: "Abstract registration" },
    { value: "rebuttal", label: "Rebuttal / author response" },
    { value: "camera_ready", label: "Camera-ready version" },
    { value: "artifact_submission", label: "Artifact submission" },
    { value: "author_registration", label: "Author registration" },
];

export const ELIGIBILITY_LABEL: Record<string, string> = {
    eligible: "Eligible for this action",
    ineligible: "Not eligible for this action",
    needs_human_resolution: "Needs your resolution",
};

export function eligibilityStatusKey(status: string): string {
    return status === "eligible" ? "passed" : status === "ineligible" ? "blocked" : "needs_human_resolution";
}

export function stageIndex(stage: string): number {
    return STAGES.indexOf(stage as (typeof STAGES)[number]);
}

/** Visible package label: unapproved exports are for author review only and say so prominently. */
export function packageLabel(p: Pick<ExportPackageEntry, "approved">): string {
    return p.approved ? "Approved (H4)" : "UNAPPROVED – for author review only";
}

export function packageStatusKey(status: string): string {
    return { building: "running", built: "complete", verified: "passed", failed: "failed" }[status] ?? status;
}

export const PACKAGE_STATUS_LABEL: Record<string, string> = {
    building: "Building",
    built: "Built (not verified against H4)",
    verified: "Verified against the signed content manifest",
    failed: "Verification failed",
};

export function emptyAuthor(corresponding = false): AuthorInput {
    return {
        name: "",
        email: null,
        affiliations: [],
        orcid: null,
        user_id: null,
        corresponding,
        contribution_roles: [],
        contribution_statement: "",
        competing_interests: "",
        funding: "",
        human_confirmed: false,
    };
}

export function authorToInput(a: AuthorEntry): AuthorInput {
    return {
        name: a.name,
        email: a.email,
        affiliations: a.affiliations,
        orcid: a.orcid,
        user_id: a.user_id,
        corresponding: a.corresponding,
        contribution_roles: a.contribution_roles,
        contribution_statement: a.contribution_statement,
        competing_interests: a.competing_interests,
        funding: a.funding,
        // The stored record only contains people the server accepted; the confirmation is asked again on every save.
        human_confirmed: false,
    };
}

export function moveItem<T>(list: T[], from: number, to: number): T[] {
    if (to < 0 || to >= list.length) return list;
    const next = [...list];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    return next;
}

/** Server problems from a 422 `invalid_authors` refusal, shown verbatim. */
export function serverProblems(details: unknown): string[] {
    if (details && typeof details === "object" && Array.isArray((details as { problems?: unknown }).problems)) {
        return ((details as { problems: unknown[] }).problems).map(String);
    }
    return [];
}

export const DISCLOSURE_LIMITS: Record<keyof Omit<Disclosures, "data_availability">, { label: string; min: number }> = {
    competing_interests: { label: "Competing interests", min: 2 },
    funding: { label: "Funding", min: 2 },
    ethics_statement: { label: "Ethics statement", min: 2 },
    ai_use: { label: "AI use (in your words)", min: 10 },
    ai_policy_text: { label: "Venue or publisher AI policy text (as published)", min: 10 },
    ai_policy_source: { label: "Policy source (URL or rule reference)", min: 4 },
    ai_policy_interpretation: { label: "Your interpretation of the policy", min: 10 },
};

/** Client-side mirror of the server's minimum lengths; the server re-validates every save. */
export function disclosureProblems(d: Disclosures): string[] {
    return (Object.keys(DISCLOSURE_LIMITS) as (keyof typeof DISCLOSURE_LIMITS)[])
        .filter((k) => (d[k] ?? "").trim().length < DISCLOSURE_LIMITS[k].min)
        .map((k) => `${DISCLOSURE_LIMITS[k].label}: at least ${DISCLOSURE_LIMITS[k].min} characters`);
}

export function emptyDisclosures(): Disclosures {
    return {
        competing_interests: "",
        funding: "",
        ethics_statement: "",
        ai_use: "",
        ai_policy_text: "",
        ai_policy_source: "",
        ai_policy_interpretation: "",
        data_availability: null,
    };
}
