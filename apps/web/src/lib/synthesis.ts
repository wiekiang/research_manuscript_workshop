/**
 * M10 evidence-synthesis and qualitative helpers (spec §2.5, §2.7, §3). The server is authoritative: the review
 * specification is frozen with the protocol, counts come from stored records, screening is a human decision and pooling
 * is computed by the platform. These helpers only shape that data for display and never invent values.
 */
import type { ApiError } from "@/lib/api/client";
import type { ReviewFlow, ReviewSpec, ReviewType, ReviewWorkspaceView, SynthesisKind } from "@/lib/api/types";

export const REVIEW_STUDY_TYPES: ReviewType[] = ["systematic_review", "meta_analysis", "mapping_review", "scoping_review", "tertiary_review"];
export const QUALITATIVE_STUDY_TYPES = ["empirical_qualitative"];
export const SPEC_SECTION = "review_specification";

export function isReviewStudyType(t: string | null | undefined): t is ReviewType {
    return !!t && (REVIEW_STUDY_TYPES as string[]).includes(t);
}

/** The synthesis each review type must use (mirrors ReviewSpec._consistent on the server). */
export function allowedSyntheses(t: ReviewType): SynthesisKind[] {
    if (t === "systematic_review") return ["narrative", "meta_analysis"];
    if (t === "meta_analysis") return ["meta_analysis"];
    if (t === "tertiary_review") return ["review_of_reviews"];
    return ["map"];
}

export const SYNTHESIS_LABEL: Record<SynthesisKind, string> = {
    narrative: "Narrative synthesis",
    meta_analysis: "Meta-analysis (statistical pooling)",
    map: "Classification / charting map",
    review_of_reviews: "Synthesis of reviews (with overlap assessment)",
};

export const DEFAULT_RATINGS = ["low", "some_concerns", "high", "unclear"];

export function emptySpec(t: ReviewType): ReviewSpec {
    const synthesis = allowedSyntheses(t)[0];
    return {
        review_type: t,
        question: "",
        searches: [{ provider: "crossref", query: "", year_from: null, year_to: null, max_results: 50 }],
        inclusion_criteria: [""],
        exclusion_reasons: [""],
        extraction_form: [],
        appraisal_tool: null,
        appraisal_items: [],
        synthesis,
        effect_measure: synthesis === "meta_analysis" ? "" : null,
        pooling_model: synthesis === "meta_analysis" ? "random_dl" : null,
        charting_scheme: [],
        reporting_standard: t === "scoping_review" ? "PRISMA-ScR" : t === "mapping_review" ? "" : "PRISMA 2020",
    };
}

/** Parse the stored section; an unparsable value starts a fresh specification (the raw text is never discarded silently). */
export function parseSpec(raw: string | undefined, t: ReviewType): { spec: ReviewSpec; parseError: string | null } {
    if (!raw || !raw.trim()) return { spec: emptySpec(t), parseError: null };
    try {
        const parsed = JSON.parse(raw) as Partial<ReviewSpec>;
        return { spec: { ...emptySpec(t), ...parsed, review_type: t }, parseError: null };
    } catch (e) {
        return { spec: emptySpec(t), parseError: `The saved review specification is not valid JSON (${(e as Error).message}).` };
    }
}

/** Serialize for the protocol section: blank list entries are dropped, numbers stay numbers. */
export function serializeSpec(s: ReviewSpec): string {
    const clean: ReviewSpec = {
        ...s,
        inclusion_criteria: s.inclusion_criteria.map((x) => x.trim()).filter(Boolean),
        exclusion_reasons: s.exclusion_reasons.map((x) => x.trim()).filter(Boolean),
        extraction_form: s.extraction_form.filter((f) => f.key.trim()),
        appraisal_items: s.appraisal_items.filter((i) => i.key.trim()).map((i) => ({ ...i, ratings: i.ratings.map((r) => r.trim()).filter(Boolean) })),
        charting_scheme: s.charting_scheme.filter((d) => d.key.trim()).map((d) => ({ ...d, categories: d.categories.map((c) => c.trim()).filter(Boolean) })),
        effect_measure: s.synthesis === "meta_analysis" ? s.effect_measure : null,
        pooling_model: s.synthesis === "meta_analysis" ? s.pooling_model : null,
    };
    return JSON.stringify(clean);
}

/** One row per flow box, in PRISMA order; values are the server's counts, never recomputed here. */
export function flowRows(f: ReviewFlow): { key: string; label: string; value: number }[] {
    return [
        { key: "identified", label: "Records identified by the specified searches", value: f.identified },
        { key: "duplicates_removed", label: "Duplicates removed", value: f.duplicates_removed },
        { key: "screened", label: "Records screened (title/abstract)", value: f.screened },
        { key: "screened_out", label: "Excluded at title/abstract", value: f.screened_out },
        { key: "awaiting_screening", label: "Awaiting title/abstract decision", value: f.awaiting_screening },
        { key: "full_text_assessed", label: "Full texts assessed", value: f.full_text_assessed },
        { key: "awaiting_full_text", label: "Awaiting full-text decision", value: f.awaiting_full_text },
        { key: "excluded_full_text", label: "Excluded at full text", value: f.excluded_full_text },
        { key: "included", label: "Studies included", value: f.included },
    ];
}

/** Whether the server's counts reconcile (the same identities the server's flow_problems checks). */
export function flowReconciles(f: ReviewFlow): boolean {
    return (
        f.screened === f.screened_out + f.full_text_assessed + f.awaiting_full_text + f.awaiting_screening &&
        f.full_text_assessed === f.excluded_full_text + f.included &&
        f.identified - f.duplicates_removed === f.screened
    );
}

/** Exclusion reasons the protocol allows; screening may use only these. */
export function exclusionOptions(spec: ReviewSpec): string[] {
    return spec.exclusion_reasons.filter((r) => r.trim());
}

export type StoredKind = "flow" | "meta_analysis" | "map" | "overlap";

export function synthesisKindFor(spec: ReviewSpec): StoredKind | null {
    if (spec.synthesis === "meta_analysis") return "meta_analysis";
    if (spec.synthesis === "map") return "map";
    if (spec.synthesis === "review_of_reviews") return "overlap";
    return null;
}

/** A stored synthesis is stale when the extraction records changed after it was computed. */
export function isStale(view: ReviewWorkspaceView, kind: StoredKind): boolean {
    const s = view.syntheses[kind];
    return !!s && s.inputs_hash !== view.current_inputs_hash;
}

export function problemsOf(err: unknown, code: string): string[] {
    const e = err as ApiError | undefined;
    const d = e?.details as { problems?: unknown } | undefined;
    return e?.code === code && Array.isArray(d?.problems) ? d.problems.map(String) : [];
}

export const SYNTHESIS_REFUSAL_HINT: Record<string, string> = {
    h2_required: "The review workspace uses only the specification frozen with the protocol at H2. Draft and freeze the protocol under Methodology & protocol.",
    no_review_spec: "The frozen protocol has no review specification. Amend the protocol to add one.",
    invalid_review_spec: "The frozen review specification does not validate; amend the protocol.",
    provider_unavailable: "A specified source is not enabled. Amend the protocol to use an enabled source.",
    not_a_record: "Only records retrieved by the protocol's searches can be screened.",
    reason_not_in_protocol: "Choose one of the exclusion reasons frozen in the protocol.",
    not_included_at_title_abstract: "Only records included at title/abstract are assessed in full text.",
    not_included: "Extract only from studies included after full-text screening.",
    invalid_extraction: "Fix the listed problems: values need a verified passage of the study or 'not reported'.",
    quote_not_in_source: "Copy the quote exactly as it appears in the source.",
    unknown_code: "Every theme code must exist in this project's codebook.",
};

export function synthesisHint(err: unknown): string | null {
    const code = (err as ApiError | undefined)?.code;
    return code ? (SYNTHESIS_REFUSAL_HINT[code] ?? null) : null;
}

/** Refusals that mean "this workspace is not set up yet" (shown as a neutral notice, not an error). */
export const SETUP_CODES = ["h2_required", "no_review_spec", "invalid_review_spec"];

export function fmt(n: number | undefined | null, digits = 4): string {
    return n == null || Number.isNaN(n) ? "—" : n.toFixed(digits);
}
