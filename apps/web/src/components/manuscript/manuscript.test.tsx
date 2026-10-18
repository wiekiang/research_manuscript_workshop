import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { assuranceStatus } from "@/components/method/results-panel";
import { h2BlockingReasons } from "@/components/method/protocol-workspace";
import { stageFields } from "@/components/method/stage-forms";
import { ApiError } from "@/lib/api/client";
import type { ContentSection, ContentSpan, SpanRecord } from "@/lib/api/types";
import { candidateAction, fromEditable, interpretConflict, originLabel, sortIssues, toEditable } from "@/lib/manuscript";
import { DiffView } from "./candidates-panel";
import { SpanView } from "./span-view";

const span = (over: Partial<ContentSpan> = {}): ContentSpan => ({
    span_id: "S-1",
    text: "Pip is the most widely used package manager for data science.",
    kind: "prior_work",
    claim_ids: [],
    result_keys: [],
    origin: "ai",
    protected: false,
    ...over,
});

const record = (over: Partial<SpanRecord> = {}): SpanRecord => ({
    span_id: "S-1",
    section: "related_work",
    kind: "prior_work",
    text: "x",
    claim_ids: [],
    result_keys: [],
    origin: "ai",
    protected: false,
    status: "issues",
    issues: [],
    ...over,
});

describe("span provenance and issues", () => {
    it("renders issues most severe first with severity in text, not color alone", () => {
        render(
            <SpanView
                projectId="p"
                span={span()}
                record={record({
                    issues: [
                        { code: "unsupported_factual_span", severity: "major", message: "factual sentence without a claim or result link (unresolved-claim queue)" },
                        { code: "gap_overstated", severity: "blocker", message: "the researcher assessed the gap as partially_addressed" },
                    ],
                })}
            />,
        );
        const issues = screen.getAllByTestId("span-issue");
        expect(issues.map((i) => i.dataset.severity)).toEqual(["blocker", "major"]);
        expect(within(issues[0]).getByText("Blocker")).toBeInTheDocument();
        expect(within(issues[1]).getByText("Major")).toBeInTheDocument();
        expect(screen.getByText(/the researcher assessed the gap as partially_addressed/)).toBeInTheDocument();
        expect(screen.getByText("Prior work (must cite a claim)")).toBeInTheDocument();
    });

    it("never labels AI-drafted text as human-authored", () => {
        render(<SpanView projectId="p" span={span({ origin: "ai", protected: false })} />);
        expect(screen.getByTestId("span-origin")).toHaveTextContent("AI-drafted");
        expect(screen.queryByText(/Written by a researcher/)).toBeNull();
        expect(screen.queryByText("Protected")).toBeNull();
        expect(originLabel("ai").label).toBe("AI-drafted");
        expect(originLabel("anything-else").label).toBe("AI-drafted");
    });

    it("shows human, protected text and its cited claim/result IDs", () => {
        render(<SpanView projectId="p" span={span({ origin: "human", protected: true, kind: "observed_result", claim_ids: ["CLM-0002"], result_keys: ["RES-001"] })} record={record({ status: "ok" })} />);
        expect(screen.getByTestId("span-origin")).toHaveTextContent("Written by a researcher");
        expect(screen.getByText("Protected")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "CLM-0002" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "RES-001" })).toBeInTheDocument();
    });

    it("sorts blockers before majors and minors", () => {
        const s = sortIssues([
            { code: "a", severity: "minor", message: "" },
            { code: "b", severity: "major", message: "" },
            { code: "c", severity: "blocker", message: "" },
        ]);
        expect(s.map((x) => x.severity)).toEqual(["blocker", "major", "minor"]);
    });
});

describe("stale candidates are never applied silently", () => {
    it("allows apply only for a ready candidate generated against the current version", () => {
        expect(candidateAction({ status: "ready", base_version_id: "v2" }, "v2")).toBe("apply");
        expect(candidateAction({ status: "ready", base_version_id: "v1" }, "v2")).toBe("merge");
        expect(candidateAction({ status: "stale", base_version_id: "v1" }, "v2")).toBe("merge");
        for (const st of ["pending", "applied", "merged", "rejected", "failed"]) expect(candidateAction({ status: st, base_version_id: "v2" }, "v2")).toBe("none");
    });

    it("interprets 409 stale_candidate and merge_required with their diffs", () => {
        const diff = [{ section: "introduction", diff: "--- introduction (current)\n+++ introduction (proposed)\n-A\n+B\n" }];
        const stale = interpretConflict(new ApiError(409, "stale_candidate", "the manuscript changed while this draft was generated; review the diff and merge", { diff_vs_current: diff, current_version: 2 }, null));
        expect(stale?.kind).toBe("stale_candidate");
        expect(stale?.diff).toEqual(diff);
        expect(stale?.currentVersion).toBe(2);
        const mr = interpretConflict(new ApiError(409, "merge_required", "the candidate regenerates sections containing human-authored text", { sections: ["introduction"], diff_vs_current: diff }, null));
        expect(mr?.kind).toBe("merge_required");
        expect(mr?.sections).toEqual(["introduction"]);
        expect(interpretConflict(new ApiError(422, "unprocessable", "x", null, null))).toBeNull();
        expect(interpretConflict(new ApiError(409, "wrong_state", "x", null, null))).toBeNull();
    });

    it("renders added and removed lines of the diff", () => {
        render(<DiffView diffs={[{ section: "introduction", diff: "--- a\n+++ b\n-old sentence\n+new sentence\n" }]} />);
        expect(screen.getByText("-old sentence")).toHaveClass("text-error-primary");
        expect(screen.getByText("+new sentence")).toHaveClass("text-success-primary");
    });
});

describe("section editing payload", () => {
    const section: ContentSection = {
        key: "introduction",
        heading: "Introduction",
        tables: [],
        figures: [],
        paragraphs: [{ spans: [span({ span_id: "S-a", text: "Old.", kind: "framing" }), span({ span_id: "S-b", text: "Cited.", claim_ids: ["CLM-0001"] })] }],
    };

    it("round-trips spans, drops empty sentences and keeps claim links", () => {
        const ed = toEditable(section);
        ed[0][0].text = "  ";
        ed[0].push({ span_id: "", text: "New sentence.", kind: "hypothesis", claim_ids: "", result_keys: "RES-001, RES-002" });
        const out = fromEditable(section, ed);
        expect(out.paragraphs[0].spans.map((s) => s.span_id)).toEqual(["S-b", ""]);
        expect(out.paragraphs[0].spans[0].claim_ids).toEqual(["CLM-0001"]);
        expect(out.paragraphs[0].spans[1].result_keys).toEqual(["RES-001", "RES-002"]);
    });
});

describe("M5 honest labels", () => {
    it("maps a pending assessment to 'pending', never to a level", () => {
        expect(assuranceStatus({ assessment: null, assurance_level: "declared" })).toBe("assurance_pending");
        expect(assuranceStatus({ assessment: { assurance_level: "independently_checked" } as never, assurance_level: "declared" })).toBe("assurance_independently_checked");
    });

    it("lists every unmet H2 precondition", () => {
        const r = h2BlockingReasons({
            missing_sections: ["metrics"],
            ethics_blockers: ["accept the ethics and rights declaration"],
            cost_flags: [],
            review: ["independent methodology review not performed (request it, or record a waiver with rationale)"],
            unresolved_blocker_issues: [{ severity: "blocker", section: "sample_or_data_selection", issue: "Eight pipelines cannot support a binomial test.", rationale: "", proposed_fix: "" }],
            ready_for_h2: false,
        });
        expect(r).toEqual([
            "section 'Metrics' is empty",
            "accept the ethics and rights declaration",
            "independent methodology review not performed (request it, or record a waiver with rationale)",
            "unresolved blocker in Sample or data selection: Eight pipelines cannot support a binomial test.",
        ]);
    });

    it("asks for the structured fields the data-provenance validators read", () => {
        expect(stageFields({ validator_ids: ["v.data_provenance_complete", "v.rights_declared"] }).map((f) => f.key)).toEqual(["data_origin", "selection_criteria", "pii_classification", "rights"]);
        expect(stageFields({ validator_ids: ["v.result_manifest_complete"] })).toEqual([]);
    });
});
