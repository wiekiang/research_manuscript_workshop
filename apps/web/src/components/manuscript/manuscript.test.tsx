import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { assuranceStatus } from "@/components/method/results-panel";
import { h2BlockingReasons } from "@/components/method/protocol-workspace";
import { stageFields } from "@/components/method/stage-forms";
import { ApiError, api } from "@/lib/api/client";
import type { ContentSection, ContentSpan, ManuscriptVersion, SpanRecord, TableIssue } from "@/lib/api/types";
import { candidateAction, fromEditable, interpretConflict, originLabel, sortIssues, tableAnchor, tableIssuesFor, toEditable, toEditableTables } from "@/lib/manuscript";
import { DiffView } from "./candidates-panel";
import { SectionEditor } from "./section-editor";
import { SpanView, TableView } from "./span-view";

afterEach(() => vi.restoreAllMocks());

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

describe("table result-key issues are located and actionable", () => {
    // Verbatim shape of checks_summary.table_issues as committed by the API (asserted in
    // apps/api/tests/test_m6_manuscript_tables.py) and specified by contracts check_tables: span-issue fields
    // (code/severity/message) plus the locating fields (section/table_index/caption). Typed against the contract
    // types so a drift in either breaks this file at compile time.
    const unknownKey: TableIssue = {
        section: "results",
        table_index: 1,
        caption: "Broken",
        code: "unknown_table_result",
        severity: "blocker",
        message: "RES-404 is not a committed result; the table would render with no rows for it",
    };
    const checks: ManuscriptVersion["checks"] = { spans: 9, spans_with_issues: 0, unresolved_claims: 0, blockers: 1, abstract_words: 10, table_issues: [unknownKey] };

    it("matches issues to a table by the contract's locating fields (section + table_index)", () => {
        expect(tableIssuesFor("results", 1, checks)).toEqual([unknownKey]);
        expect(tableIssuesFor("results", 0, checks)).toEqual([]);
        expect(tableIssuesFor("discussion", 1, checks)).toEqual([]);
        expect(tableIssuesFor("results", 1, { blockers: 0 })).toEqual([]); // older versions without table_issues
    });

    it("shows an invalid table as a blocker with the offending key and where it occurs", () => {
        render(<TableView projectId="p" sectionKey="results" index={1} caption="Broken" resultKeys={["RES-404"]} issues={[unknownKey]} />);
        const table = screen.getByTestId("manuscript-table");
        expect(table.id).toBe(tableAnchor("results", 1)); // linkable from the sidebar queue
        expect(table.dataset.section).toBe("results");
        expect(table.dataset.status).toBe("blocked");
        const issue = screen.getByTestId("span-issue");
        expect(issue.dataset.code).toBe("unknown_table_result");
        expect(within(issue).getByText("Blocker")).toBeInTheDocument();
        expect(screen.getByText(/RES-404 is not a committed result/)).toBeInTheDocument();
    });

    it("shows a corrected table as clean", () => {
        render(<TableView projectId="p" sectionKey="results" index={0} caption="Accuracy" resultKeys={["RES-001"]} issues={[]} />);
        expect(screen.getByTestId("manuscript-table").dataset.status).toBe("ok");
        expect(screen.queryByTestId("span-issue")).toBeNull();
        expect(screen.getByRole("link", { name: "RES-001" })).toBeInTheDocument();
    });

    it("lets the editor correct the key: the PATCH payload carries the fixed result_keys", () => {
        const section: ContentSection = {
            key: "results",
            heading: "Results",
            paragraphs: [],
            figures: [],
            tables: [
                { caption: "Accuracy", result_keys: ["RES-001"] },
                { caption: "Broken", result_keys: ["RES-404"] },
            ],
        };
        const tables = toEditableTables(section);
        expect(tables).toEqual([
            { caption: "Accuracy", result_keys: "RES-001" },
            { caption: "Broken", result_keys: "RES-404" },
        ]);
        tables[1].result_keys = "RES-001"; // the correction
        expect(fromEditable(section, [], tables).tables).toEqual([
            { caption: "Accuracy", result_keys: ["RES-001"] },
            { caption: "Broken", result_keys: ["RES-001"] },
        ]);
        // Emptying a table removes it from the payload; not passing tables keeps the committed ones untouched.
        expect(fromEditable(section, [], [tables[0], { caption: "  ", result_keys: "" }]).tables).toEqual([{ caption: "Accuracy", result_keys: ["RES-001"] }]);
        expect(fromEditable(section, []).tables).toEqual(section.tables);
    });

    const resultsSection = (tables: ContentSection["tables"]): ContentSection => ({ key: "results", heading: "Results", paragraphs: [], figures: [], tables });

    /** The tables of the single section in the PATCH body sent by the editor. */
    const savedTables = (patch: ReturnType<typeof vi.spyOn>) => (patch.mock.calls[0][1] as { sections: ContentSection[] }).sections[0].tables;

    it("offers a table editor for a section with no tables and saves the new caption and result keys", async () => {
        const patch = vi.spyOn(api, "patch").mockResolvedValue({} as never);
        render(<SectionEditor manuscriptId="m" section={resultsSection([])} expectedVersion={2} onSaved={() => {}} onCancel={() => {}} onReload={() => {}} />);

        // The fieldset is offered even though the section has no tables yet.
        expect(screen.getByTestId("tables-editor")).toBeInTheDocument();
        expect(screen.getByText("This section has no tables.")).toBeInTheDocument();
        expect(screen.queryAllByTestId("table-editor")).toHaveLength(0);

        fireEvent.click(screen.getByRole("button", { name: "Add a table" }));
        const row = screen.getByTestId("table-editor");
        expect(row.dataset.status).toBe("ok");
        expect(screen.queryByText("This section has no tables.")).toBeNull();
        fireEvent.change(within(row).getByRole("textbox", { name: /Table 1 caption/ }), { target: { value: "Restoration accuracy" } });
        fireEvent.change(within(row).getByRole("textbox", { name: /Result keys/ }), { target: { value: "RES-001, RES-002" } });
        fireEvent.click(screen.getByRole("button", { name: "Save as a new version" }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        expect(patch.mock.calls[0][0]).toBe("/v1/manuscripts/m");
        // Existing editable payload shape: {caption, result_keys[]} on the section, keys split from the input.
        expect(savedTables(patch)).toEqual([{ caption: "Restoration accuracy", result_keys: ["RES-001", "RES-002"] }]);
        expect((patch.mock.calls[0][1] as { expected_version: number }).expected_version).toBe(2);
    });

    it("adds a table alongside existing ones without disturbing their recorded issues", async () => {
        const patch = vi.spyOn(api, "patch").mockResolvedValue({} as never);
        const section = resultsSection([
            { caption: "Accuracy", result_keys: ["RES-001"] },
            { caption: "Broken", result_keys: ["RES-404"] },
        ]);
        render(<SectionEditor manuscriptId="m" section={section} expectedVersion={2} tableIssues={[unknownKey]} onSaved={() => {}} onCancel={() => {}} onReload={() => {}} />);

        fireEvent.click(screen.getByRole("button", { name: "Add a table" }));
        const rows = screen.getAllByTestId("table-editor");
        expect(rows).toHaveLength(3);
        // The committed table keeps its blocker; the new row is not committed, so it adopts no issue.
        expect(rows.map((r) => r.dataset.status)).toEqual(["ok", "blocked", "ok"]);
        expect(within(rows[1]).getByText(/RES-404 is not a committed result/)).toBeInTheDocument();
        expect(within(rows[2]).queryByTestId("span-issue")).toBeNull();

        fireEvent.change(within(rows[2]).getByRole("textbox", { name: /Table 3 caption/ }), { target: { value: "Latency" } });
        fireEvent.change(within(rows[2]).getByRole("textbox", { name: /Result keys/ }), { target: { value: "RES-002" } });
        fireEvent.click(screen.getByRole("button", { name: "Save as a new version" }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        expect(savedTables(patch)).toEqual([
            { caption: "Accuracy", result_keys: ["RES-001"] },
            { caption: "Broken", result_keys: ["RES-404"] },
            { caption: "Latency", result_keys: ["RES-002"] },
        ]);
    });

    it("preserves an annotated span's claim IDs and result keys when only the table is edited", async () => {
        const patch = vi.spyOn(api, "patch").mockResolvedValue({} as never);
        const annotated = span({ span_id: "S-ann", text: "Version records restored most of the audited pipelines.", kind: "observed_result", claim_ids: ["CLM-0001"], result_keys: ["RES-001"] });
        const section: ContentSection = {
            key: "results",
            heading: "Results",
            figures: [],
            paragraphs: [{ spans: [annotated] }],
            tables: [{ caption: "Broken", result_keys: ["RES-404"] }],
        };
        render(<SectionEditor manuscriptId="m" section={section} expectedVersion={2} tableIssues={[{ ...unknownKey, table_index: 0 }]} onSaved={() => {}} onCancel={() => {}} onReload={() => {}} />);

        // Touch only the table's result keys; the sentence and its annotations are left alone.
        fireEvent.change(within(screen.getByTestId("table-editor")).getByRole("textbox", { name: /Result keys/ }), { target: { value: "RES-001" } });
        fireEvent.click(screen.getByRole("button", { name: "Save as a new version" }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        const saved = (patch.mock.calls[0][1] as { sections: ContentSection[] }).sections[0];
        expect(saved.tables).toEqual([{ caption: "Broken", result_keys: ["RES-001"] }]);
        // The span round-trips with its evidence links and identity intact, so the server keeps its provenance.
        expect(saved.paragraphs[0].spans).toHaveLength(1);
        expect(saved.paragraphs[0].spans[0]).toMatchObject({
            span_id: "S-ann",
            text: "Version records restored most of the audited pipelines.",
            kind: "observed_result",
            claim_ids: ["CLM-0001"],
            result_keys: ["RES-001"],
        });
    });

    it("keeps an existing table's issue attached to it after the rows above it shift", () => {
        const section = resultsSection([
            { caption: "Accuracy", result_keys: ["RES-001"] },
            { caption: "Broken", result_keys: ["RES-404"] },
        ]);
        render(<SectionEditor manuscriptId="m" section={section} expectedVersion={2} tableIssues={[unknownKey]} onSaved={() => {}} onCancel={() => {}} onReload={() => {}} />);

        // Removing the clean table moves "Broken" from position 1 to 0; its issue is located by its committed
        // index, so it must follow the table rather than the position.
        fireEvent.click(within(screen.getAllByTestId("table-editor")[0]).getByRole("button", { name: "Remove table" }));
        const rows = screen.getAllByTestId("table-editor");
        expect(rows).toHaveLength(1);
        expect(within(rows[0]).getByRole("textbox", { name: /Result keys/ })).toHaveValue("RES-404");
        expect(rows[0].dataset.status).toBe("blocked");
        expect(within(rows[0]).getByText(/RES-404 is not a committed result/)).toBeInTheDocument();
    });

    it("saves the corrected key when an invalid table is fixed in the editor", async () => {
        const patch = vi.spyOn(api, "patch").mockResolvedValue({} as never);
        const section = resultsSection([
            { caption: "Accuracy", result_keys: ["RES-001"] },
            { caption: "Broken", result_keys: ["RES-404"] },
        ]);
        render(<SectionEditor manuscriptId="m" section={section} expectedVersion={2} tableIssues={[unknownKey]} onSaved={() => {}} onCancel={() => {}} onReload={() => {}} />);

        const broken = screen.getAllByTestId("table-editor")[1];
        expect(broken.dataset.status).toBe("blocked");
        fireEvent.change(within(broken).getByRole("textbox", { name: /Result keys/ }), { target: { value: "RES-001" } });
        fireEvent.click(screen.getByRole("button", { name: "Save as a new version" }));

        await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
        expect(savedTables(patch)).toEqual([
            { caption: "Accuracy", result_keys: ["RES-001"] },
            { caption: "Broken", result_keys: ["RES-001"] },
        ]);
    });

    it("surfaces the committed version's table issues inside the section editor, on the right table", () => {
        const section: ContentSection = {
            key: "results",
            heading: "Results",
            paragraphs: [],
            figures: [],
            tables: [
                { caption: "Accuracy", result_keys: ["RES-001"] },
                { caption: "Broken", result_keys: ["RES-404"] },
            ],
        };
        render(<SectionEditor manuscriptId="m" section={section} expectedVersion={2} tableIssues={[unknownKey]} onSaved={() => {}} onCancel={() => {}} onReload={() => {}} />);
        const rows = screen.getAllByTestId("table-editor");
        expect(rows.map((r) => r.dataset.status)).toEqual(["ok", "blocked"]);
        expect(within(rows[1]).getByText(/RES-404 is not a committed result/)).toBeInTheDocument();
        expect(within(rows[1]).getByRole("textbox", { name: /Result keys/ })).toHaveValue("RES-404");
        expect(within(rows[0]).queryByTestId("span-issue")).toBeNull();
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
