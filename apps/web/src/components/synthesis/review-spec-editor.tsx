"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import type { ReviewSpec, ReviewType, SynthesisKind } from "@/lib/api/types";
import { humanize } from "@/lib/format";
import { DEFAULT_RATINGS, SYNTHESIS_LABEL, allowedSyntheses, parseSpec, serializeSpec } from "@/lib/synthesis";

interface Props {
    studyType: ReviewType;
    /** The protocol section value (JSON text). */
    value: string | undefined;
    onChange: (json: string) => void;
}

function numOrNull(v: string): number | null {
    const n = Number(v);
    return v.trim() === "" || Number.isNaN(n) ? null : n;
}

function StringList({ label, hint, items, onChange, addLabel }: { label: string; hint?: string; items: string[]; onChange: (v: string[]) => void; addLabel: string }) {
    return (
        <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium text-secondary">{label}</legend>
            {hint && <p className="text-xs text-tertiary">{hint}</p>}
            {items.map((it, i) => (
                <div key={i} className="flex items-end gap-2">
                    <div className="flex-1">
                        <Input aria-label={`${label} ${i + 1}`} value={it} onChange={(v) => onChange(items.map((x, j) => (j === i ? v : x)))} />
                    </div>
                    <Button size="sm" color="link-gray" onClick={() => onChange(items.filter((_, j) => j !== i))}>
                        Remove
                    </Button>
                </div>
            ))}
            <div>
                <Button size="sm" color="secondary" onClick={() => onChange([...items, ""])}>
                    {addLabel}
                </Button>
            </div>
        </fieldset>
    );
}

/**
 * Structured editor for the protocol section `review_specification`. It is frozen with the protocol at H2, so the
 * exact queries, sources, criteria, exclusion reasons, forms and synthesis plan cannot change without an amendment.
 * The server validates it (shown verbatim under the protocol); this editor only builds the JSON.
 */
export function ReviewSpecEditor({ studyType, value, onChange }: Props) {
    const initial = parseSpec(value, studyType);
    const [spec, setSpec] = useState<ReviewSpec>(initial.spec);
    const parseError = initial.parseError;

    useEffect(() => {
        setSpec(parseSpec(value, studyType).spec);
        // Only re-seed when the stored value changes identity (a new protocol version), not on our own edits.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [studyType]);

    const update = (next: ReviewSpec) => {
        setSpec(next);
        onChange(serializeSpec(next));
    };
    const set = <K extends keyof ReviewSpec>(k: K, v: ReviewSpec[K]) => update({ ...spec, [k]: v });
    const syntheses = allowedSyntheses(studyType);
    const needsAppraisal = ["systematic_review", "meta_analysis", "tertiary_review"].includes(studyType);

    return (
        <section data-testid="review-spec-editor" aria-label="Review specification" className="flex flex-col gap-4 rounded-xl bg-secondary p-4 ring-1 ring-secondary">
            <div className="flex flex-col gap-1">
                <h3 className="text-md font-semibold text-primary">Review specification</h3>
                <p className="text-sm text-tertiary">
                    Frozen with the protocol at H2. Searches run exactly as written; screening may only exclude with the reasons listed here; extraction and appraisal use these
                    forms; the platform computes the synthesis. Saved in the protocol section <code>review_specification</code>.
                </p>
                {parseError && <p className="text-sm text-warning-primary">{parseError}</p>}
            </div>
            <TextArea label="Review question" isRequired value={spec.question} onChange={(v) => set("question", v)} rows={2} />

            <fieldset className="flex flex-col gap-3">
                <legend className="text-sm font-medium text-secondary">Searches (exact query strings, as executed)</legend>
                {spec.searches.map((s, i) => (
                    <div key={i} data-testid="spec-search" className="grid gap-2 rounded-lg bg-primary p-3 ring-1 ring-secondary sm:grid-cols-6">
                        <div className="sm:col-span-2">
                            <Input label="Source" value={s.provider} onChange={(v) => set("searches", spec.searches.map((x, j) => (j === i ? { ...x, provider: v } : x)))} hint="e.g. crossref, openaire" />
                        </div>
                        <div className="sm:col-span-4">
                            <Input label="Exact query" value={s.query} onChange={(v) => set("searches", spec.searches.map((x, j) => (j === i ? { ...x, query: v } : x)))} />
                        </div>
                        <Input label="From year" inputMode="numeric" value={s.year_from?.toString() ?? ""} onChange={(v) => set("searches", spec.searches.map((x, j) => (j === i ? { ...x, year_from: numOrNull(v) } : x)))} />
                        <Input label="To year" inputMode="numeric" value={s.year_to?.toString() ?? ""} onChange={(v) => set("searches", spec.searches.map((x, j) => (j === i ? { ...x, year_to: numOrNull(v) } : x)))} />
                        <Input label="Max results" inputMode="numeric" value={String(s.max_results)} onChange={(v) => set("searches", spec.searches.map((x, j) => (j === i ? { ...x, max_results: numOrNull(v) ?? 50 } : x)))} />
                        <div className="flex items-end sm:col-span-3">
                            <Button size="sm" color="link-gray" onClick={() => set("searches", spec.searches.filter((_, j) => j !== i))}>
                                Remove search
                            </Button>
                        </div>
                    </div>
                ))}
                <div>
                    <Button size="sm" color="secondary" onClick={() => set("searches", [...spec.searches, { provider: "crossref", query: "", year_from: null, year_to: null, max_results: 50 }])}>
                        Add a search
                    </Button>
                </div>
            </fieldset>

            <StringList label="Inclusion criteria" items={spec.inclusion_criteria} onChange={(v) => set("inclusion_criteria", v)} addLabel="Add a criterion" />
            <StringList
                label="Exclusion reasons"
                hint="Screening can exclude a record only with one of these reasons."
                items={spec.exclusion_reasons}
                onChange={(v) => set("exclusion_reasons", v)}
                addLabel="Add an exclusion reason"
            />

            <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium text-secondary">Extraction form</legend>
                {spec.extraction_form.map((f, i) => (
                    <div key={i} className="flex flex-wrap items-end gap-2">
                        <Input label="Field key" value={f.key} onChange={(v) => set("extraction_form", spec.extraction_form.map((x, j) => (j === i ? { ...x, key: v } : x)))} />
                        <Input label="Label" value={f.label} onChange={(v) => set("extraction_form", spec.extraction_form.map((x, j) => (j === i ? { ...x, label: v } : x)))} />
                        <NativeSelect
                            label="Required"
                            value={f.required ? "yes" : "no"}
                            onChange={(e) => set("extraction_form", spec.extraction_form.map((x, j) => (j === i ? { ...x, required: e.target.value === "yes" } : x)))}
                            options={[
                                { label: "Required", value: "yes" },
                                { label: "Optional", value: "no" },
                            ]}
                        />
                        <Button size="sm" color="link-gray" onClick={() => set("extraction_form", spec.extraction_form.filter((_, j) => j !== i))}>
                            Remove
                        </Button>
                    </div>
                ))}
                <div>
                    <Button size="sm" color="secondary" onClick={() => set("extraction_form", [...spec.extraction_form, { key: "", label: "", required: true }])}>
                        Add an extraction field
                    </Button>
                </div>
            </fieldset>

            <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium text-secondary">Appraisal {needsAppraisal ? "(required for this review type)" : "(optional)"}</legend>
                <Input label="Appraisal tool" value={spec.appraisal_tool ?? ""} onChange={(v) => set("appraisal_tool", v || null)} hint="e.g. RoB 2, ROBINS-I, AMSTAR 2" />
                {spec.appraisal_items.map((it, i) => (
                    <div key={i} className="flex flex-wrap items-end gap-2">
                        <Input label="Item key" value={it.key} onChange={(v) => set("appraisal_items", spec.appraisal_items.map((x, j) => (j === i ? { ...x, key: v } : x)))} />
                        <Input label="Item label" value={it.label} onChange={(v) => set("appraisal_items", spec.appraisal_items.map((x, j) => (j === i ? { ...x, label: v } : x)))} />
                        <Input
                            label="Ratings (comma-separated)"
                            value={it.ratings.join(", ")}
                            onChange={(v) => set("appraisal_items", spec.appraisal_items.map((x, j) => (j === i ? { ...x, ratings: v.split(",").map((r) => r.trim()) } : x)))}
                        />
                        <Button size="sm" color="link-gray" onClick={() => set("appraisal_items", spec.appraisal_items.filter((_, j) => j !== i))}>
                            Remove
                        </Button>
                    </div>
                ))}
                <div>
                    <Button size="sm" color="secondary" onClick={() => set("appraisal_items", [...spec.appraisal_items, { key: "", label: "", ratings: [...DEFAULT_RATINGS] }])}>
                        Add an appraisal item
                    </Button>
                </div>
            </fieldset>

            <NativeSelect
                label="Synthesis"
                value={spec.synthesis}
                onChange={(e) => {
                    const s = e.target.value as SynthesisKind;
                    update({
                        ...spec,
                        synthesis: s,
                        effect_measure: s === "meta_analysis" ? (spec.effect_measure ?? "") : null,
                        pooling_model: s === "meta_analysis" ? (spec.pooling_model ?? "random_dl") : null,
                    });
                }}
                options={syntheses.map((s) => ({ label: SYNTHESIS_LABEL[s], value: s }))}
            />
            {spec.synthesis === "meta_analysis" && (
                <div className="grid gap-3 sm:grid-cols-2">
                    <Input label="Effect measure" isRequired value={spec.effect_measure ?? ""} onChange={(v) => set("effect_measure", v)} hint="e.g. log odds ratio, standardized mean difference" />
                    <NativeSelect
                        label="Pooling model"
                        value={spec.pooling_model ?? "random_dl"}
                        onChange={(e) => set("pooling_model", e.target.value as ReviewSpec["pooling_model"])}
                        options={[
                            { label: "Random effects (DerSimonian-Laird)", value: "random_dl" },
                            { label: "Fixed effect (inverse variance)", value: "fixed" },
                        ]}
                    />
                </div>
            )}
            {spec.synthesis === "map" && (
                <fieldset className="flex flex-col gap-2">
                    <legend className="text-sm font-medium text-secondary">Charting scheme</legend>
                    {spec.charting_scheme.map((d, i) => (
                        <div key={i} className="flex flex-wrap items-end gap-2">
                            <Input label="Dimension key" value={d.key} onChange={(v) => set("charting_scheme", spec.charting_scheme.map((x, j) => (j === i ? { ...x, key: v } : x)))} />
                            <Input label="Dimension label" value={d.label} onChange={(v) => set("charting_scheme", spec.charting_scheme.map((x, j) => (j === i ? { ...x, label: v } : x)))} />
                            <Input
                                label="Categories (comma-separated)"
                                value={d.categories.join(", ")}
                                onChange={(v) => set("charting_scheme", spec.charting_scheme.map((x, j) => (j === i ? { ...x, categories: v.split(",").map((c) => c.trim()) } : x)))}
                            />
                            <Button size="sm" color="link-gray" onClick={() => set("charting_scheme", spec.charting_scheme.filter((_, j) => j !== i))}>
                                Remove
                            </Button>
                        </div>
                    ))}
                    <div>
                        <Button size="sm" color="secondary" onClick={() => set("charting_scheme", [...spec.charting_scheme, { key: "", label: "", categories: [] }])}>
                            Add a charting dimension
                        </Button>
                    </div>
                </fieldset>
            )}
            <Input label="Reporting standard" isRequired value={spec.reporting_standard} onChange={(v) => set("reporting_standard", v)} hint={`Review type: ${humanize(studyType)}`} />
        </section>
    );
}
