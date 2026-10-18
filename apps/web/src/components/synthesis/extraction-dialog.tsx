"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { api } from "@/lib/api/client";
import type { PassageEntry, ReviewRecord, ReviewSpec } from "@/lib/api/types";
import { Refusal } from "./refusal";

interface FieldValue {
    value: string;
    passage_id: string;
    not_reported: boolean;
}

interface Props {
    projectId: string;
    record: ReviewRecord | null;
    spec: ReviewSpec;
    /** Verified passages of the whole project; only this study's verified passages are offered. */
    passages: PassageEntry[];
    onOpenChange: (open: boolean) => void;
    onSaved: () => void;
}

function num(v: string): number | undefined {
    const n = Number(v);
    return v.trim() === "" || Number.isNaN(n) ? undefined : n;
}

/**
 * Extraction and appraisal for one included study. A value must point at a verified passage of this study or be
 * marked "not reported"; the server rejects anything else and its problems are listed verbatim.
 */
export function ExtractionDialog({ projectId, record, spec, passages, onOpenChange, onSaved }: Props) {
    const own = passages.filter((p) => record && p.paper_id === record.paper_id && p.verified_in_source);
    const [values, setValues] = useState<Record<string, FieldValue>>({});
    const [appraisal, setAppraisal] = useState<Record<string, { rating: string; rationale: string }>>({});
    const [estimate, setEstimate] = useState("");
    const [variance, setVariance] = useState("");
    const [charting, setCharting] = useState<Record<string, string>>({});
    const [primary, setPrimary] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const fv = (k: string): FieldValue => values[k] ?? { value: "", passage_id: "", not_reported: false };
    const setFv = (k: string, patch: Partial<FieldValue>) => setValues((v) => ({ ...v, [k]: { ...fv(k), ...patch } }));

    const save = async () => {
        if (!record) return;
        setBusy(true);
        setError(undefined);
        const body: Record<string, unknown> = {
            paper_id: record.paper_id,
            values: Object.fromEntries(
                spec.extraction_form.map((f) => {
                    const v = fv(f.key);
                    return [f.key, v.not_reported ? { not_reported: true } : { value: v.value || null, passage_id: v.passage_id || null }];
                }),
            ),
            appraisal: Object.fromEntries(Object.entries(appraisal).filter(([, a]) => a.rating)),
            charting,
            primary_studies: primary
                .split("\n")
                .map((x) => x.trim())
                .filter(Boolean),
        };
        if (spec.synthesis === "meta_analysis") body.effect = { estimate: num(estimate), variance: num(variance) };
        try {
            await api.post(`/v1/projects/${projectId}/review/extractions`, body);
            onOpenChange(false);
            onSaved();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <DialogShell
            isOpen={!!record}
            onOpenChange={onOpenChange}
            size="lg"
            title={`Extract and appraise: ${record?.title ?? ""}`}
            description="Link each value to a verified passage of this study, or mark it not reported. Saving supersedes any earlier record for this study; a synthesis computed before the change becomes stale."
            footer={
                <>
                    <Button color="secondary" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button isLoading={busy} onClick={save}>
                        Save extraction
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {spec.extraction_form.length > 0 && (
                    <fieldset className="flex flex-col gap-3">
                        <legend className="text-sm font-medium text-secondary">Extraction form</legend>
                        {own.length === 0 && <p className="text-xs text-tertiary">This study has no verified passages; link values after adding its full text, or mark them not reported.</p>}
                        {spec.extraction_form.map((f) => (
                            <div key={f.key} data-testid="extraction-field" className="flex flex-col gap-2 rounded-lg p-3 ring-1 ring-secondary">
                                <p className="text-sm font-medium text-primary">
                                    {f.label} {f.required ? "" : "(optional)"}
                                </p>
                                <Checkbox isSelected={fv(f.key).not_reported} onChange={(v) => setFv(f.key, { not_reported: v })} label="Not reported in this study" />
                                {!fv(f.key).not_reported && (
                                    <>
                                        <Input label={`${f.label}: value`} value={fv(f.key).value} onChange={(v) => setFv(f.key, { value: v })} />
                                        <NativeSelect
                                            label={`${f.label}: supporting passage`}
                                            value={fv(f.key).passage_id}
                                            onChange={(e) => setFv(f.key, { passage_id: e.target.value })}
                                            options={[{ label: "Select a verified passage", value: "" }, ...own.map((p) => ({ label: p.quote.slice(0, 120), value: p.id }))]}
                                        />
                                    </>
                                )}
                            </div>
                        ))}
                    </fieldset>
                )}
                {spec.appraisal_items.length > 0 && (
                    <fieldset className="flex flex-col gap-3">
                        <legend className="text-sm font-medium text-secondary">Appraisal{spec.appraisal_tool ? ` (${spec.appraisal_tool})` : ""}</legend>
                        {spec.appraisal_items.map((it) => (
                            <div key={it.key} className="grid gap-2 sm:grid-cols-2">
                                <NativeSelect
                                    label={it.label}
                                    value={appraisal[it.key]?.rating ?? ""}
                                    onChange={(e) => setAppraisal((a) => ({ ...a, [it.key]: { rating: e.target.value, rationale: a[it.key]?.rationale ?? "" } }))}
                                    options={[{ label: "Select a rating", value: "" }, ...it.ratings.map((r) => ({ label: r, value: r }))]}
                                />
                                <Input
                                    label={`${it.label}: rationale`}
                                    value={appraisal[it.key]?.rationale ?? ""}
                                    onChange={(v) => setAppraisal((a) => ({ ...a, [it.key]: { rating: a[it.key]?.rating ?? "", rationale: v } }))}
                                />
                            </div>
                        ))}
                    </fieldset>
                )}
                {spec.synthesis === "meta_analysis" && (
                    <fieldset className="grid gap-2 sm:grid-cols-2">
                        <legend className="text-sm font-medium text-secondary">Effect ({spec.effect_measure})</legend>
                        <Input label="Effect estimate" inputMode="decimal" value={estimate} onChange={setEstimate} />
                        <Input label="Variance" inputMode="decimal" value={variance} onChange={setVariance} hint="Must be positive" />
                    </fieldset>
                )}
                {spec.synthesis === "map" &&
                    spec.charting_scheme.map((d) => (
                        <NativeSelect
                            key={d.key}
                            label={`Charting: ${d.label}`}
                            value={charting[d.key] ?? ""}
                            onChange={(e) => setCharting((c) => ({ ...c, [d.key]: e.target.value }))}
                            options={[{ label: "Select a category", value: "" }, ...d.categories.map((c) => ({ label: c, value: c }))]}
                        />
                    ))}
                {spec.synthesis === "review_of_reviews" && (
                    <TextArea label="Primary studies included in this review (one identifier per line)" value={primary} onChange={setPrimary} rows={4} />
                )}
                <Refusal error={error} />
            </div>
        </DialogShell>
    );
}
