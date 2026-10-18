/**
 * Single mapping of manuscript span/candidate states to honest labels, and the pure helpers the editor uses to build
 * PATCH payloads and to interpret apply/merge refusals. Mirrors contracts/src/rp_contracts/manuscript.py.
 */
import { ApiError } from "@/lib/api/client";
import type { ContentSection, ContentSpan, GenerationCandidate, SectionDiff, SpanIssue, SpanKind, SpanRecord } from "@/lib/api/types";

export const SPAN_KINDS: SpanKind[] = ["framing", "prior_work", "method", "observed_result", "interpretation", "hypothesis", "limitation", "contribution_statement"];

export const SPAN_KIND_LABEL: Record<SpanKind, string> = {
    prior_work: "Prior work (must cite a claim)",
    observed_result: "Observed result (must cite a result)",
    method: "Method",
    interpretation: "Interpretation",
    hypothesis: "Hypothesis",
    limitation: "Limitation",
    contribution_statement: "Contribution statement",
    framing: "Framing",
};

/** Factual kinds must link to a claim or a committed result (contracts FACTUAL). */
export const FACTUAL_KINDS: SpanKind[] = ["prior_work", "observed_result"];

/** Provenance of a sentence. AI text is never shown as human-authored, whatever its other properties. */
export function originLabel(origin: string): { label: string; description: string } {
    if (origin === "human") return { label: "Written by a researcher", description: "Human-authored text; protected from regeneration" };
    return { label: "AI-drafted", description: "Drafted by the section writer agent from the frozen brief; review before relying on it" };
}

export type IssueTone = "error" | "warning" | "gray";

export function issueTone(severity: string): IssueTone {
    if (severity === "blocker") return "error";
    if (severity === "major") return "warning";
    return "gray";
}

export function severityLabel(severity: string): string {
    if (severity === "blocker") return "Blocker";
    if (severity === "major") return "Major";
    if (severity === "minor") return "Minor";
    return severity;
}

/** Most severe first, so blockers are read before majors. */
export function sortIssues(issues: SpanIssue[]): SpanIssue[] {
    const rank = (s: string) => (s === "blocker" ? 0 : s === "major" ? 1 : 2);
    return [...issues].sort((a, b) => rank(a.severity) - rank(b.severity));
}

export function spanStatusKey(span: Pick<SpanRecord, "status">): string {
    return `span_${span.status}`;
}

export function candidateStatusKey(status: string): string {
    return `candidate_${status}`;
}

/**
 * A candidate is applicable directly only when it is ready and was generated against the current version. Anything
 * generated against an older version is stale and needs an explicit merge (never a silent overwrite).
 */
export function candidateAction(c: Pick<GenerationCandidate, "status" | "base_version_id">, currentVersionId: string): "apply" | "merge" | "none" {
    if (c.status === "ready" && c.base_version_id === currentVersionId) return "apply";
    if (c.status === "ready" || c.status === "stale") return "merge";
    return "none";
}

export interface ApplyRefusal {
    kind: "stale_candidate" | "merge_required" | "stale_version";
    message: string;
    diff: SectionDiff[];
    sections: string[];
    currentVersion: number | null;
}

/** Interpret a 409 from apply/merge/edit; returns null for other errors (shown with ErrorAlert). */
export function interpretConflict(err: unknown): ApplyRefusal | null {
    if (!(err instanceof ApiError) || err.status !== 409) return null;
    if (!["stale_candidate", "merge_required", "stale_version"].includes(err.code)) return null;
    const d = (err.details ?? {}) as { diff_vs_current?: SectionDiff[]; sections?: string[]; current_version?: number };
    return {
        kind: err.code as ApplyRefusal["kind"],
        message: err.message,
        diff: Array.isArray(d.diff_vs_current) ? d.diff_vs_current : [],
        sections: Array.isArray(d.sections) ? d.sections : [],
        currentVersion: typeof d.current_version === "number" ? d.current_version : null,
    };
}

/** Spans of one version grouped by section key, in document order. */
export function spansBySection(spans: SpanRecord[]): Record<string, SpanRecord[]> {
    const out: Record<string, SpanRecord[]> = {};
    for (const s of spans) (out[s.section] ??= []).push(s);
    return out;
}

/** Issues recorded for a span id in the current version (content spans carry no issues; span records do). */
export function issuesFor(spanId: string, records: SpanRecord[]): SpanRecord | undefined {
    return records.find((r) => r.span_id === spanId);
}

export interface EditableSpan {
    span_id: string;
    text: string;
    kind: SpanKind;
    claim_ids: string;
    result_keys: string;
}

export function toEditable(section: ContentSection): EditableSpan[][] {
    return section.paragraphs.map((p) =>
        p.spans.map((s) => ({ span_id: s.span_id, text: s.text, kind: s.kind, claim_ids: s.claim_ids.join(", "), result_keys: s.result_keys.join(", ") })),
    );
}

function splitIds(v: string): string[] {
    return v
        .split(/[,\s]+/)
        .map((x) => x.trim())
        .filter(Boolean);
}

/**
 * Build the PATCH section from edited spans. Provenance (origin/protected) is decided by the server: unchanged text
 * keeps its recorded origin, changed or new text becomes human-authored. Empty sentences and paragraphs are dropped.
 */
export function fromEditable(section: ContentSection, paragraphs: EditableSpan[][]): ContentSection {
    return {
        ...section,
        paragraphs: paragraphs
            .map((p) => ({
                spans: p
                    .filter((s) => s.text.trim())
                    .map(
                        (s): ContentSpan => ({
                            span_id: s.span_id,
                            text: s.text.trim(),
                            kind: s.kind,
                            claim_ids: splitIds(s.claim_ids),
                            result_keys: splitIds(s.result_keys),
                            origin: "human",
                            protected: true,
                        }),
                    ),
            }))
            .filter((p) => p.spans.length > 0),
    };
}

export const VERSION_ORIGIN_LABEL: Record<string, string> = {
    initial: "Empty section skeleton",
    human_edit: "Edited by a researcher",
    candidate_applied: "Generated draft applied",
    merge: "Generated draft merged by a researcher",
};

export const GAP_SECTION_LABEL: Record<string, string> = {
    abstract: "Abstract",
    introduction: "Introduction",
    discussion: "Discussion",
    conclusion: "Conclusion",
};
