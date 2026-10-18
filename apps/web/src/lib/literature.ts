/**
 * Plain-language mappings for literature, evidence and claim states. Kept pure so they are unit-tested: the wording
 * here is part of the product's honesty guarantees (e.g. a not-found DOI is never called a "missing paper", and a
 * model-assisted check is never presented as human verification).
 */
import type { IdentityVerification, PaperEntry, VerificationEntry } from "@/lib/api/types";

export interface Label {
    status: string;
    label: string;
    detail: string;
}

/** Identity of a cited work, checked deterministically against the DOI registry. */
export function identityLabel(status: string, v: IdentityVerification | undefined): Label {
    switch (status) {
        case "verified":
            return {
                status: "identity_verified",
                label: "Identity verified",
                detail: `Matches the ${registryName(v?.source)} record${v?.basis ? `: ${v.basis}` : ""}`,
            };
        case "mismatch":
            return {
                status: "identity_mismatch",
                label: "Identity mismatch",
                detail: `The cited title or year does not match the ${registryName(v?.source)} record for this DOI${
                    v?.title_similarity !== undefined ? ` (title similarity ${v.title_similarity}${v.title_coverage !== undefined ? `, coverage ${v.title_coverage}` : ""})` : ""
                }`,
            };
        case "not_found":
            return {
                status: "identity_not_found",
                label: "DOI not registered — possible fabricated or mistyped DOI",
                detail: v?.reason ?? "The DOI is not registered with Crossref or DataCite.",
            };
        default:
            if (v?.outcome === "unavailable") {
                return { status: "identity_unavailable", label: "Identity check unavailable", detail: v.error ?? "The DOI registry could not be reached; the check will need to run again." };
            }
            return { status: "identity_unverified", label: "Identity not yet verified", detail: "No deterministic DOI check has completed for this record." };
    }
}

function registryName(source: string | undefined): string {
    if (source === "datacite") return "DataCite";
    if (source === "crossref") return "Crossref";
    return source ?? "registry";
}

export const FULLTEXT_LABELS: Record<string, { label: string; status: string }> = {
    none: { label: "No full text", status: "ft_none" },
    located: { label: "Full-text location found", status: "ft_located" },
    retrieved: { label: "Full text stored", status: "ft_retrieved" },
    parsed: { label: "Full text reviewed", status: "ft_parsed" },
    not_permitted: { label: "Full text not permitted", status: "ft_not_permitted" },
    inaccessible: { label: "Full text inaccessible", status: "ft_inaccessible" },
};

export function fulltextLabel(p: Pick<PaperEntry, "fulltext_status" | "rights">): Label {
    const spec = FULLTEXT_LABELS[p.fulltext_status] ?? { label: p.fulltext_status, status: "ft_none" };
    return { status: spec.status, label: spec.label, detail: p.rights?.basis ?? "" };
}

export const CLAIM_STATUS: Record<string, { label: string; status: string }> = {
    verified: { label: "Meets the verification policy", status: "claim_verified" },
    unverified: { label: "Not yet verified", status: "claim_unverified" },
    contested: { label: "Contested", status: "claim_contested" },
    rejected: { label: "Rejected", status: "rejected" },
};

/** Which method produced a verification record and, for model checks, which provider. */
export function verificationProvider(v: Pick<VerificationEntry, "method" | "verifier" | "evidence">): string | null {
    if (v.method !== "model_assisted") return null;
    const fromEvidence = typeof v.evidence?.provider === "string" ? (v.evidence.provider as string) : null;
    return fromEvidence ?? (v.verifier.includes(":") ? v.verifier.split(":")[0] : v.verifier) ?? null;
}

/** Provider of an extraction recorded as "provider:model". */
export function extractorProvider(extractedBy: string, method: string): string | null {
    if (method !== "model_assisted") return null;
    return extractedBy.split(":")[0] || null;
}

export const PROVIDER_STATUS: Record<string, { label: string; status: string }> = {
    ok: { label: "Searched", status: "succeeded" },
    partial: { label: "Partial response", status: "warning" },
    rate_limited: { label: "Rate limited", status: "failed_retryable" },
    access_denied: { label: "Access denied", status: "failed" },
    payment_required: { label: "Payment required", status: "failed" },
    unavailable: { label: "Unavailable", status: "failed" },
    unsupported: { label: "Unsupported", status: "not_performed" },
    disabled: { label: "Disabled", status: "not_performed" },
    refused: { label: "Not used", status: "not_performed" },
};

export const CLAIM_KINDS = ["literature", "observed_result", "interpretation", "hypothesis", "limitation"] as const;
export const CLAIM_CATEGORIES = ["descriptive", "numerical", "comparative", "causal", "novelty", "ethics_policy", "central_conclusion", "identity"] as const;
export const CATEGORY_LABEL: Record<string, string> = {
    identity: "Identity",
    descriptive: "Descriptive",
    numerical: "Numerical / result",
    comparative: "Comparative",
    causal: "Causal",
    novelty: "Novelty",
    ethics_policy: "Ethics / policy",
    central_conclusion: "Central conclusion",
};

export const FEASIBILITY_STATUS: Record<string, { label: string; status: string }> = {
    feasible: { label: "Feasible (advisory)", status: "feas_feasible" },
    at_risk: { label: "At risk (advisory)", status: "feas_at_risk" },
    infeasible: { label: "Infeasible (advisory)", status: "feas_infeasible" },
};

export const TRACK_ACCEPTS: Record<string, string> = {
    yes: "Listed by the selected track",
    no: "Not listed by the selected track",
    unknown: "Track acceptance unknown",
};

/** The coverage report must never claim completeness. */
export function safeCoverageLevel(level: string): string {
    return level.toLowerCase().includes("comprehensive") ? "limited" : level;
}

/** Human-readable string for a requirement id, falling back to the id itself. */
export function requirementText(id: string, requirements: Record<string, string>): string {
    if (id.startsWith("any:")) {
        return `At least one of: ${id
            .slice(4)
            .split("|")
            .map((r) => requirements[r] ?? r)
            .join(" / ")}`;
    }
    return requirements[id] ?? id.replace(/_/g, " ");
}
