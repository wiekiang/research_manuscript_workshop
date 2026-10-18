/**
 * M9 experiment helpers (spec §2.9). A run becomes a result only when it succeeded AND a separate validator recomputed
 * its metrics from the stored raw outputs; failed, timed-out or sandbox-unavailable runs are visible but never results.
 * The server is authoritative (`promotable`, refusals); these helpers only keep the UI from implying otherwise.
 */
import type { ApiError } from "@/lib/api/client";
import type { DataNature, ExperimentPlanSpec, ExperimentRunEntry, PlanInputSpec } from "@/lib/api/types";

export const DATA_NATURES: DataNature[] = ["empirical", "synthetic", "simulated"];
export const DATA_NATURE_LABEL: Record<DataNature, string> = {
    empirical: "Empirical",
    synthetic: "Synthetic",
    simulated: "Simulated",
};
export const RUN_TYPE_LABEL = { exploratory: "Exploratory", confirmatory: "Confirmatory" } as const;
export const FAILED_STATES = ["failed", "timed_out", "sandbox_unavailable", "cancelled"];
export const ACTIVE_RUN_STATES = ["queued", "running"];

/** Mirrors the server rule: promotable only for a succeeded, independently recomputed, not yet promoted run. */
export function canPromote(run: ExperimentRunEntry): boolean {
    return run.promotable && run.status === "succeeded" && run.recomputation?.status === "passed" && !run.result_manifest_id;
}

/** True when a run's metrics may be shown as candidate findings (never for failed or unrecomputed runs). */
export function metricsAreFindings(run: ExperimentRunEntry): boolean {
    return run.status === "succeeded" && run.recomputation?.status === "passed";
}

export function canRerun(run: ExperimentRunEntry): boolean {
    return run.status === "succeeded";
}

export function recomputationKey(run: ExperimentRunEntry): string {
    if (run.status !== "succeeded" || !run.recomputation) return "recompute_not_performed";
    return `recompute_${run.recomputation.status}`;
}

export function inputNatures(inputs: PlanInputSpec[]): DataNature[] {
    return Array.from(new Set(inputs.map((i) => i.data_nature)));
}

export function shortImage(ref: string): string {
    return ref.startsWith("sha256:") ? `${ref.slice(0, 19)}…` : ref;
}

/** Problems from an `invalid_plan` refusal, verbatim. */
export function planProblems(err: unknown): string[] {
    const e = err as ApiError | undefined;
    const details = e?.details as { problems?: unknown } | undefined;
    if (e?.code === "invalid_plan" && Array.isArray(details?.problems)) return details.problems.map(String);
    return [];
}

export const EXPERIMENT_REFUSAL_HINT: Record<string, string> = {
    h2_required: "Freeze a protocol at H2 first (Methodology & protocol). Experiments run only under the frozen protocol.",
    h2_not_current: "The H2 approval is no longer current; re-freeze the protocol before planning runs.",
    plan_not_approved: "The project owner must approve this plan before it can run.",
    budget_exceeded: "The estimate exceeds the remaining project budget. A project owner must raise the cap on the Costs page.",
    protocol_changed: "The frozen protocol changed since this plan was drafted; draft a new plan.",
    wrong_state: "Runs happen while research is active or under outcome review.",
    bad_rerun: "A reproduction rerun needs a succeeded run of the same plan.",
    run_not_succeeded: "Only a succeeded run can become a result.",
    not_recomputed: "The validator must recompute the metrics from the raw outputs before the run can become a result.",
    already_promoted: "This run is already registered as a result.",
    declaration_required: "Accept the exact declaration shown.",
};

export function experimentHint(err: unknown): string | null {
    const code = (err as ApiError | undefined)?.code;
    return code ? (EXPERIMENT_REFUSAL_HINT[code] ?? null) : null;
}

export function emptyPlan(): ExperimentPlanSpec {
    return {
        title: "",
        code_artifact_id: "",
        code_path: "main.py",
        entrypoint: ["python", "main.py", "--seed", "{seed}"],
        inputs: [],
        image: "",
        seed: 0,
        limits: { cpus: 1, memory_mb: 1024, timeout_s: 600 },
        run_type: "confirmatory",
        metrics: [{ name: "accuracy" }],
        tolerance: 1e-9,
        predictions_path: "out/predictions.csv",
        metrics_path: "out/metrics.json",
        sample_size: null,
        data_origin: "",
        data_rights: "",
        limitations: "",
    };
}
