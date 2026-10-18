import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api/client";
import type { ExperimentPlanEntry, ExperimentRunEntry } from "@/lib/api/types";
import { canPromote, metricsAreFindings, planProblems } from "@/lib/experiments";
import { PlanCard } from "./plan-card";
import { ReproductionTable, RunCard } from "./run-card";

afterEach(() => vi.restoreAllMocks());

const run = (over: Partial<ExperimentRunEntry> = {}): ExperimentRunEntry => ({
    id: "r1aaaaaa-0000",
    status: "succeeded",
    rerun_of: null,
    task_id: "t1",
    exit_code: 0,
    duration_s: 1.25,
    reported_metrics: { accuracy: 0.75 },
    recomputation: { status: "passed", validator: "rp-experiment-validator/1", detail: "every planned metric was recomputed from the raw predictions", checks: [{ id: "recompute:accuracy[None]", status: "passed", detail: "recomputed 0.7500 vs reported 0.7500 (tolerance 0.001)" }] },
    reproduction: null,
    failure_reason: null,
    run_manifest_artifact_id: "m1",
    raw_output_artifact_id: "o1",
    predictions_artifact_id: "p1",
    log_artifact_id: "l1",
    recomputation_artifact_id: "c1",
    result_manifest_id: null,
    created_at: "2026-10-18T01:00:00Z",
    promotable: true,
    ...over,
});

const plan = (over: Partial<ExperimentPlanEntry> = {}): ExperimentPlanEntry => ({
    id: "plan1",
    plan_number: 1,
    title: "Restoration classifier",
    status: "approved",
    run_type: "confirmatory",
    synthetic: false,
    image_ref: "sha256:81d4e66c6640c6a0dce663f3094d0578e2d771ab0f186ed4972e9fa09f783cda",
    code_hash: "a".repeat(64),
    input_hashes: { "data/labels.csv": "b".repeat(64) },
    protocol_hash: "c".repeat(64),
    estimate_cents: 10,
    spec: {
        title: "Restoration classifier",
        code_artifact_id: "code1",
        code_path: "main.py",
        entrypoint: ["python", "main.py", "--seed", "{seed}"],
        inputs: [{ artifact_id: "d1", path: "data/labels.csv", data_nature: "empirical" }],
        image: "python-sci:1",
        seed: 7,
        limits: { cpus: 1, memory_mb: 512, timeout_s: 60 },
        run_type: "confirmatory",
        metrics: [{ name: "accuracy" }],
        tolerance: 1e-9,
        predictions_path: "out/predictions.csv",
        metrics_path: "out/metrics.json",
        sample_size: 8,
        data_origin: "eight public pipelines",
        data_rights: "MIT",
        limitations: "small",
    },
    artifact_id: "plan-art",
    approved_at: "2026-10-18T00:59:00Z",
    rerun_command: "POST /v1/experiment-plans/plan1/runs",
    declaration: "I approve running exactly this code.",
    runs: [],
    ...over,
});

describe("failed runs never become results", () => {
    for (const status of ["failed", "timed_out", "sandbox_unavailable", "cancelled"] as const) {
        it(`${status} run is not promotable and its values are not findings`, () => {
            const r = run({ status, promotable: true, failure_reason: "the program exited with code 1", reported_metrics: { accuracy: 0.99 } });
            expect(canPromote(r)).toBe(false);
            expect(metricsAreFindings(r)).toBe(false);
            render(<RunCard projectId="p" run={r} canEdit onChanged={() => {}} />);
            expect(screen.getByTestId("run-failure")).toHaveTextContent("cannot become a finding");
            expect(screen.queryByRole("button", { name: "Register as a result" })).toBeNull();
            expect(screen.queryByTestId("reported-metrics")).toBeNull();
            expect(screen.queryByText(/accuracy = 0.99/)).toBeNull();
        });
    }

    it("a succeeded run whose recomputation failed is labelled and not promotable", () => {
        const r = run({ promotable: false, reported_metrics: { accuracy: 0.99 }, recomputation: { status: "failed", validator: "v", checks: [] } });
        expect(canPromote(r)).toBe(false);
        render(<RunCard projectId="p" run={r} canEdit onChanged={() => {}} />);
        expect(screen.getByTestId("reported-metrics")).toHaveAttribute("data-findings", "false");
        expect(screen.getByTestId("reported-metrics")).toHaveTextContent("not a finding");
        expect(screen.getByText("Recomputation disagrees")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Register as a result" })).toBeNull();
    });

    it("even if the server flag were set, the UI does not offer promotion without passed recomputation", () => {
        expect(canPromote(run({ recomputation: null }))).toBe(false);
        expect(canPromote(run({ result_manifest_id: "res" }))).toBe(false);
        expect(canPromote(run())).toBe(true);
    });

    it("shows promotion refusals verbatim", async () => {
        vi.spyOn(api, "post").mockRejectedValue(new ApiError(409, "not_recomputed", "metrics must be independently recomputed from raw outputs first", null, "req1"));
        render(<RunCard projectId="p" run={run()} canEdit onChanged={() => {}} />);
        fireEvent.click(screen.getByRole("button", { name: "Register as a result" }));
        await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("metrics must be independently recomputed from raw outputs first"));
    });
});

describe("labels", () => {
    it("labels exploratory runs and synthetic/simulated inputs, never as empirical", () => {
        const p = plan({
            run_type: "exploratory",
            synthetic: true,
            spec: { ...plan().spec, run_type: "exploratory", inputs: [{ artifact_id: "d1", path: "data/sim.csv", data_nature: "simulated" }] },
        });
        render(<PlanCard projectId="p" plan={p} tasks={[]} isOwner canEdit onChanged={() => {}} />);
        expect(screen.getByTestId("plan-run-type")).toHaveTextContent("Exploratory");
        expect(screen.getByText(/do not present results from this plan as confirmatory/)).toBeInTheDocument();
        expect(screen.getByTestId("plan-synthetic")).toHaveTextContent("cannot stand in for empirical findings");
        const natures = screen.getAllByTestId("plan-data-nature").map((n) => n.getAttribute("data-nature"));
        expect(natures).toEqual(["simulated"]);
        expect(screen.queryByText("Empirical data")).toBeNull();
    });

    it("confirmatory empirical plan shows its pinned image, hashes and rerun command", () => {
        render(<PlanCard projectId="p" plan={plan()} tasks={[]} isOwner canEdit onChanged={() => {}} />);
        expect(screen.getByTestId("plan-run-type")).toHaveTextContent("Confirmatory");
        expect(screen.queryByTestId("plan-synthetic")).toBeNull();
        expect(screen.getByText(/python-sci:1 · sha256:81d4e66c6640/)).toBeInTheDocument();
        expect(screen.getByText("POST /v1/experiment-plans/plan1/runs")).toBeInTheDocument();
    });

    it("draft plans cannot run; the owner sees the exact declaration", () => {
        render(<PlanCard projectId="p" plan={plan({ status: "draft" })} tasks={[]} isOwner canEdit onChanged={() => {}} />);
        expect(screen.queryByRole("button", { name: "Start run" })).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Review and approve" }));
        expect(screen.getByTestId("plan-declaration")).toHaveTextContent("I approve running exactly this code.");
    });
});

describe("reproduction", () => {
    it("renders each metric with first run, rerun, difference and tolerance verdict", () => {
        render(
            <ReproductionTable
                reproduction={{ tolerance: 0.001, match: false, rows: [{ metric: "accuracy", first: 0.75, rerun: 0.76, difference: 0.01, within_tolerance: false }] }}
            />,
        );
        expect(screen.getByTestId("reproduction")).toHaveAttribute("data-match", "false");
        expect(screen.getByText("Not reproduced")).toBeInTheDocument();
        const row = screen.getByTestId("reproduction-row");
        expect(within(row).getByText("0.75")).toBeInTheDocument();
        expect(within(row).getByText("0.76")).toBeInTheDocument();
        expect(within(row).getByText("0.01")).toBeInTheDocument();
        expect(within(row).getByText("No")).toBeInTheDocument();
    });

    it("a matching rerun shows as reproduced in the run card", () => {
        const r = run({ rerun_of: "r0", reproduction: { tolerance: 1e-9, match: true, rows: [{ metric: "accuracy", first: 0.75, rerun: 0.75, difference: 0, within_tolerance: true }] } });
        render(<RunCard projectId="p" run={r} canEdit onChanged={() => {}} />);
        expect(screen.getByText("Reproduced")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Start reproduction rerun" })).toBeNull();
    });
});

describe("plan problems", () => {
    it("extracts invalid_plan problems verbatim and ignores other errors", () => {
        const err = new ApiError(422, "invalid_plan", "the experiment plan is not runnable", { problems: ["image ubuntu is not on the sandbox allowlist ['python-sci:1']"] }, null);
        expect(planProblems(err)).toEqual(["image ubuntu is not on the sandbox allowlist ['python-sci:1']"]);
        expect(planProblems(new ApiError(422, "h2_required", "x", null, null))).toEqual([]);
    });
});
