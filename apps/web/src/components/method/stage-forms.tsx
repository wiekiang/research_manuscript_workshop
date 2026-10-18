"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { ContributionEntry, ResultEntry, StageDefinitionEntry } from "@/lib/api/types";

/** Structured fields a stage validator reads (method.py VALIDATORS); other stages take a description plus links. */
const VALIDATOR_FIELDS: Record<string, { key: string; label: string; kind: "text" | "pii" }[]> = {
    "v.data_provenance_complete": [
        { key: "data_origin", label: "Data origin", kind: "text" },
        { key: "selection_criteria", label: "Selection criteria", kind: "text" },
        { key: "pii_classification", label: "Personal data classification", kind: "pii" },
    ],
    "v.rights_declared": [{ key: "rights", label: "Data rights / licence", kind: "text" }],
};

export function stageFields(stage: Pick<StageDefinitionEntry, "validator_ids">) {
    return stage.validator_ids.flatMap((v) => VALIDATOR_FIELDS[v] ?? []);
}

interface Props {
    projectId: string;
    stages: StageDefinitionEntry[];
    contributions: ContributionEntry[];
    results: ResultEntry[];
    canEdit: boolean;
    onChanged: () => void;
}

/** Record each required method stage in order. Validators are deterministic; prose alone cannot pass stages that need evidence. */
export function StageForms({ projectId, stages, contributions, results, canEdit, onChanged }: Props) {
    return (
        <Section title="Method stages" description="Complete the stages in order against the frozen protocol. Each submission is validated deterministically.">
            {stages.length === 0 && <p className="text-sm text-tertiary">Select a study type first.</p>}
            <ol className="flex flex-col gap-3">
                {stages.map((s, i) => (
                    <StageForm key={s.id} index={i} stage={s} projectId={projectId} contributions={contributions} results={results} canEdit={canEdit} onChanged={onChanged} />
                ))}
            </ol>
        </Section>
    );
}

function StageForm({
    index,
    stage,
    projectId,
    contributions,
    results,
    canEdit,
    onChanged,
}: {
    index: number;
    stage: StageDefinitionEntry;
    projectId: string;
    contributions: ContributionEntry[];
    results: ResultEntry[];
    canEdit: boolean;
    onChanged: () => void;
}) {
    const [open, setOpen] = useState(false);
    const [description, setDescription] = useState("");
    const [fields, setFields] = useState<Record<string, string>>({ pii_classification: "none" });
    const [contribIds, setContribIds] = useState<string[]>([]);
    const [resultIds, setResultIds] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [outcome, setOutcome] = useState<{ status: string; validators: { id: string; passed: boolean; detail: string }[] }>();
    const fs = stageFields(stage);
    const blocked = stage.status === "blocked_until_h2";
    const toggle = (list: string[], id: string, set: (v: string[]) => void) => set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
    const shown = outcome?.validators ?? stage.validator_results;

    return (
        <li data-testid="stage-form" data-stage={stage.id} data-status={outcome?.status ?? stage.status} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-primary">
                    {index + 1}. {stage.title}
                </span>
                <StatusBadge status={`stage_${outcome?.status ?? stage.status}`} />
                {canEdit && !blocked && (
                    <Button size="sm" color="link-color" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
                        {open ? "Close" : stage.status === "validated" ? "Record again" : "Record this stage"}
                    </Button>
                )}
            </div>
            <p className="text-xs text-tertiary">{stage.description}</p>
            {shown.length > 0 && (
                <ul className="text-xs" aria-label={`Validator results for ${stage.title}`}>
                    {shown.map((v) => (
                        <li key={v.id} className={v.passed ? "text-success-primary" : "text-error-primary"}>
                            {v.passed ? "Passed" : "Failed"}: {v.detail}
                        </li>
                    ))}
                </ul>
            )}
            {open && (
                <div className="flex flex-col gap-3 border-t border-secondary pt-3">
                    {fs.map((f) =>
                        f.kind === "pii" ? (
                            <NativeSelect
                                key={f.key}
                                label={f.label}
                                value={fields[f.key] ?? "none"}
                                onChange={(e) => setFields((x) => ({ ...x, [f.key]: e.target.value }))}
                                options={["none", "pseudonymized", "personal", "sensitive"].map((v) => ({ label: v, value: v }))}
                            />
                        ) : (
                            <Input key={f.key} label={f.label} value={fields[f.key] ?? ""} onChange={(v) => setFields((x) => ({ ...x, [f.key]: v }))} />
                        ),
                    )}
                    <TextArea label="Description" value={description} onChange={setDescription} rows={3} />
                    {contributions.length > 0 && (
                        <fieldset className="flex flex-col gap-1">
                            <legend className="text-sm font-medium text-secondary">Linked contributions</legend>
                            {contributions.map((c) => (
                                <Checkbox key={c.id} isSelected={contribIds.includes(c.id)} onChange={() => toggle(contribIds, c.id, setContribIds)} label={c.title} />
                            ))}
                        </fieldset>
                    )}
                    {results.length > 0 && (
                        <fieldset className="flex flex-col gap-1">
                            <legend className="text-sm font-medium text-secondary">Linked results</legend>
                            {results
                                .filter((r) => r.is_current)
                                .map((r) => (
                                    <Checkbox key={r.id} isSelected={resultIds.includes(r.id)} onChange={() => toggle(resultIds, r.id, setResultIds)} label={`${r.result_key} ${r.title}`} />
                                ))}
                        </fieldset>
                    )}
                    <ErrorAlert error={error} />
                    <div>
                        <Button
                            size="sm"
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    const body = {
                                        description,
                                        fields: Object.fromEntries(fs.map((f) => [f.key, fields[f.key] ?? ""])),
                                        contribution_ids: contribIds,
                                        result_ids: resultIds,
                                    };
                                    const r = await api.post<{ status: string; validators: { id: string; passed: boolean; detail: string }[] }>(
                                        `/v1/projects/${projectId}/method-stages/${stage.id}`,
                                        body,
                                    );
                                    setOutcome(r);
                                    if (r.status === "validated") setOpen(false);
                                    onChanged();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Submit stage output
                        </Button>
                    </div>
                </div>
            )}
        </li>
    );
}
