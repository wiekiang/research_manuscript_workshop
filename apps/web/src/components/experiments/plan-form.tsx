"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { ContributionEntry, DataNature, ExperimentPlanSpec } from "@/lib/api/types";
import { DATA_NATURE_LABEL, DATA_NATURES, emptyPlan, experimentHint, planProblems } from "@/lib/experiments";

interface Props {
    projectId: string;
    files: ContributionEntry[];
    images: string[];
    isOpen: boolean;
    onOpenChange: (open: boolean) => void;
    onCreated: () => void;
}

function numberOr(value: string, fallback: number): number {
    const n = Number(value);
    return value.trim() === "" || Number.isNaN(n) ? fallback : n;
}

/** Draft a plan from the project's own files. The server validates it and builds the sandbox argv itself. */
export function PlanForm({ projectId, files, images, isOpen, onOpenChange, onCreated }: Props) {
    const [plan, setPlan] = useState<ExperimentPlanSpec>(() => ({ ...emptyPlan(), image: images[0] ?? "" }));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const fileOptions = [{ label: "Select a file", value: "" }, ...files.filter((f) => f.artifact_id).map((f) => ({ label: `${f.title} (${f.type})`, value: f.artifact_id as string }))];
    const set = <K extends keyof ExperimentPlanSpec>(k: K, v: ExperimentPlanSpec[K]) => setPlan((p) => ({ ...p, [k]: v }));
    const problems = planProblems(error);
    const ready =
        plan.title.trim().length >= 3 &&
        !!plan.code_artifact_id &&
        plan.inputs.every((i) => i.artifact_id && i.path.trim()) &&
        plan.metrics.length > 0 &&
        [plan.data_origin, plan.data_rights, plan.limitations].every((t) => t.trim().length >= 3);
    const hint = experimentHint(error);

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/experiment-plans`, plan);
            onOpenChange(false);
            setPlan({ ...emptyPlan(), image: images[0] ?? "" });
            onCreated();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <DialogShell
            isOpen={isOpen}
            onOpenChange={onOpenChange}
            title="New experiment plan"
            description="A plan names the exact code, inputs, image, command, seed and limits. It runs only after the project owner approves it, under the frozen protocol, in a sandbox without network access."
            size="lg"
            footer={
                <>
                    <Button color="secondary" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button isLoading={busy} isDisabled={!ready} onClick={submit}>
                        Save draft plan
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <Input label="Title" isRequired value={plan.title} onChange={(v) => set("title", v)} />
                {!ready && <p className="text-xs text-tertiary">Give a title, data origin, data rights and limitations (3+ characters each), at least one metric, the code file, and a file and path for every input.</p>}
                <div className="grid gap-3 sm:grid-cols-2">
                    <NativeSelect label="Code file (from your contributions)" value={plan.code_artifact_id} onChange={(e) => set("code_artifact_id", e.target.value)} options={fileOptions} />
                    <Input label="Script path in the workspace" hint="ZIP archives are unpacked; a single file is placed here." value={plan.code_path} onChange={(v) => set("code_path", v)} />
                </div>

                <fieldset className="flex flex-col gap-2">
                    <legend className="text-sm font-medium text-secondary">Command (each argument separately)</legend>
                    <p className="text-xs text-tertiary">
                        The first argument must be an allowed interpreter. Write <span className="font-mono">{"{seed}"}</span> where the plan&apos;s seed should be inserted. Arguments are passed as-is, never through a shell.
                    </p>
                    {plan.entrypoint.map((arg, i) => (
                        <div key={i} className="flex items-end gap-2">
                            <div className="flex-1">
                                <Input
                                    label={`Argument ${i + 1}`}
                                    value={arg}
                                    onChange={(v) => set("entrypoint", plan.entrypoint.map((a, j) => (j === i ? v : a)))}
                                />
                            </div>
                            <Button size="sm" color="tertiary" isDisabled={plan.entrypoint.length <= 1} onClick={() => set("entrypoint", plan.entrypoint.filter((_, j) => j !== i))}>
                                Remove
                            </Button>
                        </div>
                    ))}
                    <div>
                        <Button size="sm" color="secondary" onClick={() => set("entrypoint", [...plan.entrypoint, ""])}>
                            Add argument
                        </Button>
                    </div>
                </fieldset>

                <fieldset className="flex flex-col gap-2">
                    <legend className="text-sm font-medium text-secondary">Inputs</legend>
                    {plan.inputs.length === 0 && <p className="text-xs text-tertiary">No input files.</p>}
                    {plan.inputs.map((inp, i) => (
                        <div key={i} className="grid gap-2 rounded-lg p-3 ring-1 ring-secondary sm:grid-cols-3">
                            <NativeSelect
                                label={`Input ${i + 1} file`}
                                value={inp.artifact_id}
                                onChange={(e) => set("inputs", plan.inputs.map((x, j) => (j === i ? { ...x, artifact_id: e.target.value } : x)))}
                                options={fileOptions}
                            />
                            <Input label={`Input ${i + 1} path`} value={inp.path} onChange={(v) => set("inputs", plan.inputs.map((x, j) => (j === i ? { ...x, path: v } : x)))} />
                            <NativeSelect
                                label={`Input ${i + 1} data nature`}
                                value={inp.data_nature}
                                onChange={(e) => set("inputs", plan.inputs.map((x, j) => (j === i ? { ...x, data_nature: e.target.value as DataNature } : x)))}
                                options={DATA_NATURES.map((n) => ({ label: DATA_NATURE_LABEL[n], value: n }))}
                            />
                            <div className="sm:col-span-3">
                                <Button size="sm" color="tertiary" onClick={() => set("inputs", plan.inputs.filter((_, j) => j !== i))}>
                                    Remove input
                                </Button>
                            </div>
                        </div>
                    ))}
                    <div>
                        <Button size="sm" color="secondary" onClick={() => set("inputs", [...plan.inputs, { artifact_id: "", path: "data/input.csv", data_nature: "empirical" }])}>
                            Add input
                        </Button>
                    </div>
                </fieldset>

                <div className="grid gap-3 sm:grid-cols-3">
                    <NativeSelect label="Sandbox image" value={plan.image} onChange={(e) => set("image", e.target.value)} options={images.map((i) => ({ label: i, value: i }))} />
                    <Input label="Seed" type="number" value={String(plan.seed)} onChange={(v) => set("seed", numberOr(v, 0))} />
                    <NativeSelect
                        label="Run type"
                        value={plan.run_type}
                        onChange={(e) => set("run_type", e.target.value as ExperimentPlanSpec["run_type"])}
                        options={[
                            { label: "Confirmatory (planned before running)", value: "confirmatory" },
                            { label: "Exploratory", value: "exploratory" },
                        ]}
                    />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                    <Input label="CPUs" type="number" value={String(plan.limits.cpus)} onChange={(v) => set("limits", { ...plan.limits, cpus: numberOr(v, 1) })} />
                    <Input label="Memory (MB)" type="number" value={String(plan.limits.memory_mb)} onChange={(v) => set("limits", { ...plan.limits, memory_mb: numberOr(v, 1024) })} />
                    <Input label="Time limit (s)" type="number" value={String(plan.limits.timeout_s)} onChange={(v) => set("limits", { ...plan.limits, timeout_s: numberOr(v, 600) })} />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                    <Input
                        label="Metrics (comma-separated)"
                        hint="Recomputed from the predictions file."
                        value={plan.metrics.map((m) => m.name).join(", ")}
                        onChange={(v) => set("metrics", v.split(",").map((x) => x.trim()).filter(Boolean).map((name) => ({ name })))}
                    />
                    <Input label="Reproduction tolerance (absolute)" type="number" value={String(plan.tolerance)} onChange={(v) => set("tolerance", numberOr(v, 0))} />
                    <Input label="Sample size (optional)" type="number" value={plan.sample_size === null ? "" : String(plan.sample_size)} onChange={(v) => set("sample_size", v.trim() === "" ? null : numberOr(v, 0))} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                    <Input label="Predictions file" value={plan.predictions_path} onChange={(v) => set("predictions_path", v)} />
                    <Input label="Metrics file" value={plan.metrics_path} onChange={(v) => set("metrics_path", v)} />
                </div>
                <TextArea label="Data origin" value={plan.data_origin} onChange={(v) => set("data_origin", v)} rows={2} />
                <TextArea label="Data rights" value={plan.data_rights} onChange={(v) => set("data_rights", v)} rows={2} />
                <TextArea label="Limitations" value={plan.limitations} onChange={(v) => set("limitations", v)} rows={2} />

                {problems.length > 0 && (
                    <ul data-testid="plan-problems" className="list-disc rounded-lg bg-error-primary p-3 pl-8 text-sm text-error-primary">
                        {problems.map((p) => (
                            <li key={p}>{p}</li>
                        ))}
                    </ul>
                )}
                <ErrorAlert error={error} />
                {hint && <p className="text-sm text-tertiary">{hint}</p>}
            </div>
        </DialogShell>
    );
}
