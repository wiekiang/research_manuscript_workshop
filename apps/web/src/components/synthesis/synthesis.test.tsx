import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api/client";
import type { ReviewFlow, ReviewRecord, ReviewSpec, ReviewWorkspaceView } from "@/lib/api/types";
import { h2BlockingReasons } from "@/components/method/protocol-workspace";
import { emptySpec, flowReconciles, isStale, parseSpec, serializeSpec } from "@/lib/synthesis";
import { FlowDiagram } from "./flow-diagram";
import { QualitativeWorkspace } from "./qualitative-workspace";
import { RecordsTable } from "./records-table";
import { ReviewSpecEditor } from "./review-spec-editor";
import { Refusal } from "./refusal";
import { SynthesisPanel } from "./synthesis-panel";

afterEach(() => vi.restoreAllMocks());

const flow = (over: Partial<ReviewFlow> = {}): ReviewFlow => ({
    identified: 5,
    duplicates_removed: 0,
    screened: 5,
    screened_out: 2,
    awaiting_screening: 0,
    full_text_assessed: 3,
    awaiting_full_text: 0,
    excluded_full_text: 0,
    excluded_full_text_reasons: {},
    included: 3,
    included_ids: ["p1", "p2", "p3"],
    ...over,
});

const spec: ReviewSpec = {
    ...emptySpec("meta_analysis"),
    question: "How often does recording library versions restore outputs?",
    searches: [{ provider: "crossref", query: "provenance reproducibility data pipelines", year_from: 2015, year_to: null, max_results: 25 }],
    inclusion_criteria: ["empirical study"],
    exclusion_reasons: ["not an empirical study", "no restoration outcome reported"],
    effect_measure: "log odds of restoration",
};

const record = (over: Partial<ReviewRecord> = {}): ReviewRecord => ({
    paper_id: "p9",
    title: "A record",
    doi: "10.1/x",
    title_abstract: null,
    full_text: null,
    extracted: false,
    ...over,
});

const view = (over: Partial<ReviewWorkspaceView> = {}): ReviewWorkspaceView => ({
    specification: spec,
    protocol_hash: "f".repeat(64),
    flow: flow(),
    searches: [],
    records: [],
    syntheses: {
        meta_analysis: {
            result: { status: "computed", model: "random_dl", k: 3, estimate: 0.5, se: Math.sqrt(1 / 18.75), ci_low: 0.047, ci_high: 0.953, q: 32, df: 2, tau2: 0.15, i2: 93.75, engine: "rp-synthesis/1", effect_measure: "log odds of restoration" },
            inputs_hash: "h1",
            artifact_id: "a1",
        },
    },
    current_inputs_hash: "h1",
    ...over,
});

describe("flow diagram", () => {
    it("renders the server's counts and confirms they reconcile", () => {
        render(<FlowDiagram flow={flow({ excluded_full_text_reasons: {} })} />);
        expect(within(screen.getByTestId("flow-identified")).getByText("5")).toBeInTheDocument();
        expect(within(screen.getByTestId("flow-screened-out")).getByText("2")).toBeInTheDocument();
        expect(within(screen.getByTestId("flow-included")).getByText("3")).toBeInTheDocument();
        expect(screen.getByTestId("flow-reconciles")).toHaveAttribute("data-ok", "true");
    });

    it("flags counts that do not reconcile (records awaiting screening)", () => {
        const f = flow({ screened: 5, screened_out: 1, full_text_assessed: 3, awaiting_screening: 0 });
        expect(flowReconciles(f)).toBe(false);
        render(<FlowDiagram flow={f} />);
        expect(screen.getByTestId("flow-reconciles")).toHaveAttribute("data-ok", "false");
    });

    it("lists full-text exclusion reasons with their counts", () => {
        render(<FlowDiagram flow={flow({ full_text_assessed: 3, excluded_full_text: 1, included: 2, excluded_full_text_reasons: { "no restoration outcome reported": 1 } })} />);
        expect(within(screen.getByTestId("flow-excluded-full-text")).getByText("no restoration outcome reported: 1")).toBeInTheDocument();
    });
});

describe("screening", () => {
    it("offers only the protocol's exclusion reasons and sends the chosen one", async () => {
        const post = vi.spyOn(api, "post").mockResolvedValue({});
        render(<RecordsTable projectId="pid" records={[record()]} spec={spec} includedIds={[]} canEdit onChanged={() => {}} onExtract={() => {}} />);
        const select = screen.getByLabelText(/^Exclusion reason \(title\/abstract\)/) as HTMLSelectElement;
        expect(Array.from(select.options).map((o) => o.value)).toEqual(spec.exclusion_reasons);
        fireEvent.change(select, { target: { value: "no restoration outcome reported" } });
        fireEvent.click(screen.getByRole("button", { name: /Exclude at title\/abstract/ }));
        await waitFor(() =>
            expect(post).toHaveBeenCalledWith("/v1/projects/pid/review/screening", { paper_id: "p9", stage: "title_abstract", decision: "exclude", reason: "no restoration outcome reported" }),
        );
    });

    it("full-text controls appear only after inclusion at title/abstract", () => {
        render(<RecordsTable projectId="pid" records={[record()]} spec={spec} includedIds={[]} canEdit onChanged={() => {}} onExtract={() => {}} />);
        expect(screen.queryByLabelText(/^Exclusion reason \(full text\)/)).toBeNull();
        expect(screen.getByText("Assessed only after inclusion at title/abstract")).toBeInTheDocument();
    });

    it("shows a screening refusal word for word", async () => {
        vi.spyOn(api, "post").mockRejectedValue(
            new ApiError(422, "reason_not_in_protocol", "use one of the protocol's exclusion reasons", { allowed: ["not an empirical study"] }, "req1"),
        );
        render(<RecordsTable projectId="pid" records={[record()]} spec={spec} includedIds={[]} canEdit onChanged={() => {}} onExtract={() => {}} />);
        fireEvent.click(screen.getByRole("button", { name: /Exclude at title\/abstract/ }));
        const alert = await screen.findByTestId("synthesis-refusal");
        expect(alert).toHaveTextContent("use one of the protocol's exclusion reasons");
        expect(alert).toHaveTextContent("Allowed reasons: not an empirical study");
        expect(alert).toHaveTextContent("Code reason_not_in_protocol");
    });

    it("labels decisions as human decisions", () => {
        render(
            <RecordsTable
                projectId="pid"
                records={[record({ title_abstract: { decision: "exclude", reason: "not an empirical study", method: "human", by: "u1" } })]}
                spec={spec}
                includedIds={[]}
                canEdit={false}
                onChanged={() => {}}
                onExtract={() => {}}
            />,
        );
        expect(screen.getByText("Reason: not an empirical study")).toBeInTheDocument();
        expect(screen.getByText("Human decision (human)")).toBeInTheDocument();
    });
});

describe("synthesis", () => {
    it("shows the platform-computed pooled estimate and heterogeneity", () => {
        render(<SynthesisPanel projectId="pid" view={view()} canEdit={false} onChanged={() => {}} />);
        const ma = screen.getByTestId("meta-analysis");
        expect(ma).toHaveTextContent("0.5000");
        expect(ma).toHaveTextContent("93.75%");
        expect(ma).toHaveTextContent("0.1500");
        expect(screen.queryByTestId("synthesis-stale")).toBeNull();
    });

    it("warns when extraction records changed after the synthesis was computed", () => {
        const v = view({ current_inputs_hash: "h2" });
        expect(isStale(v, "meta_analysis")).toBe(true);
        render(<SynthesisPanel projectId="pid" view={v} canEdit={false} onChanged={() => {}} />);
        expect(screen.getByTestId("synthesis-stale")).toHaveTextContent("It is not current");
    });

    it("renders not_performed pooling verbatim, never as a computed value", () => {
        const v = view({ syntheses: { meta_analysis: { result: { status: "not_performed", detail: "pooling needs at least two studies with an estimate and variance" }, inputs_hash: "h1", artifact_id: "a1" } } });
        render(<SynthesisPanel projectId="pid" view={v} canEdit={false} onChanged={() => {}} />);
        expect(screen.getByText("Not performed: pooling needs at least two studies with an estimate and variance")).toBeInTheDocument();
        expect(screen.queryByTestId("meta-analysis")).toBeNull();
    });
});

describe("refusals and specification", () => {
    it("shows setup refusals as a neutral notice with the server message verbatim", () => {
        render(<Refusal tone="notice" error={new ApiError(422, "h2_required", "the review specification is used only from the H2-frozen protocol", null, "r")} />);
        const n = screen.getByTestId("synthesis-notice");
        expect(n).toHaveAttribute("role", "status");
        expect(n).toHaveTextContent("the review specification is used only from the H2-frozen protocol");
    });

    it("lists invalid_extraction problems verbatim", () => {
        render(<Refusal error={new ApiError(422, "invalid_extraction", "the extraction record is not valid", { problems: ["outcome: link the value to a verified passage of the study, or mark it not reported"] }, "r")} />);
        expect(screen.getByTestId("synthesis-refusal")).toHaveTextContent("outcome: link the value to a verified passage of the study, or mark it not reported");
    });

    it("protocol blocking reasons keep server specification problems verbatim", () => {
        const r = h2BlockingReasons({
            missing_sections: ["hypotheses", "review_specification: Value error, meta-analysis needs an effect measure and a pooling model at "],
            ethics_blockers: [],
            cost_flags: [],
            review: [],
            unresolved_blocker_issues: [],
            ready_for_h2: false,
        });
        expect(r).toEqual(["section 'Hypotheses' is empty", "review_specification: Value error, meta-analysis needs an effect measure and a pooling model at "]);
    });

    it("round-trips the specification and drops blank list entries", () => {
        const json = serializeSpec({ ...spec, exclusion_reasons: ["not an empirical study", "  "] });
        const back = parseSpec(json, "meta_analysis").spec;
        expect(back.exclusion_reasons).toEqual(["not an empirical study"]);
        expect(back.pooling_model).toBe("random_dl");
        expect(parseSpec("{not json", "meta_analysis").parseError).toMatch(/not valid JSON/);
    });
});

describe("qualitative workspace", () => {
    it("shows an honest empty codebook state", () => {
        render(<QualitativeWorkspace projectId="pid" data={{ codes: [], segments: [], themes: [] }} sources={[]} canEdit onChanged={() => {}} />);
        expect(screen.getByTestId("qual-empty-codes")).toBeInTheDocument();
    });

    it("shows quote_not_in_source verbatim", async () => {
        vi.spyOn(api, "post").mockRejectedValue(new ApiError(422, "quote_not_in_source", "the quote was not found verbatim in the source; copy it exactly", null, "r"));
        render(
            <QualitativeWorkspace
                projectId="pid"
                data={{ codes: [{ id: "c1", code: "defensive pinning", definition: "Pinning after a bad upgrade.", segments: 0 }], segments: [], themes: [] }}
                sources={[{ id: "s1", title: "Interview P1", type: "observations" } as never]}
                canEdit
                onChanged={() => {}}
            />,
        );
        fireEvent.change(screen.getByRole("combobox", { name: /^Code/ }), { target: { value: "c1" } });
        fireEvent.change(screen.getByLabelText(/^Source\*?$/), { target: { value: "s1" } });
        fireEvent.change(screen.getByLabelText(/^Quote \(verbatim\)/), { target: { value: "we never upgrade anything" } });
        fireEvent.click(screen.getByRole("button", { name: "Add coded segment" }));
        expect(await screen.findByTestId("synthesis-refusal")).toHaveTextContent("the quote was not found verbatim in the source; copy it exactly");
    });
});

describe("review specification editor", () => {
    it("serializes exact queries, exclusion reasons and the meta-analysis plan into the protocol section", () => {
        const onChange = vi.fn();
        render(<ReviewSpecEditor studyType="meta_analysis" value={undefined} onChange={onChange} />);
        fireEvent.change(screen.getByLabelText(/^Exact query/), { target: { value: "provenance reproducibility data pipelines" } });
        fireEvent.change(screen.getByLabelText(/^Exclusion reasons 1/), { target: { value: "not an empirical study" } });
        fireEvent.change(screen.getByLabelText(/^Effect measure/), { target: { value: "log odds of restoration" } });
        const last = JSON.parse(onChange.mock.calls.at(-1)?.[0] as string) as ReviewSpec;
        expect(last.review_type).toBe("meta_analysis");
        expect(last.searches[0].query).toBe("provenance reproducibility data pipelines");
        expect(last.exclusion_reasons).toEqual(["not an empirical study"]);
        expect(last.synthesis).toBe("meta_analysis");
        expect(last.effect_measure).toBe("log odds of restoration");
        expect(last.pooling_model).toBe("random_dl");
    });

    it("offers only the synthesis types the review type allows", () => {
        render(<ReviewSpecEditor studyType="tertiary_review" value={undefined} onChange={() => {}} />);
        const synth = screen.getByRole("combobox", { name: /^Synthesis/ }) as HTMLSelectElement;
        expect(Array.from(synth.options).map((o) => o.value)).toEqual(["review_of_reviews"]);
    });
});
