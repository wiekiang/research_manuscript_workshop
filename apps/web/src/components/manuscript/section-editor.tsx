"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { ContentSection, ManuscriptVersion } from "@/lib/api/types";
import { type EditableSpan, SPAN_KINDS, SPAN_KIND_LABEL, fromEditable, interpretConflict, toEditable } from "@/lib/manuscript";

interface Props {
    manuscriptId: string;
    section: ContentSection;
    expectedVersion: number;
    onSaved: (v: ManuscriptVersion) => void;
    onCancel: () => void;
    onReload: () => void;
}

const blank = (): EditableSpan => ({ span_id: "", text: "", kind: "framing", claim_ids: "", result_keys: "" });

/**
 * Edit one section sentence by sentence. Saving sends the expected version; if the manuscript changed meanwhile the
 * API refuses (409) and nothing is overwritten. Changed or new sentences become human-authored and protected.
 */
export function SectionEditor({ manuscriptId, section, expectedVersion, onSaved, onCancel, onReload }: Props) {
    const [paras, setParas] = useState<EditableSpan[][]>(() => {
        const p = toEditable(section);
        return p.length ? p : [[blank()]];
    });
    const [summary, setSummary] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const conflict = interpretConflict(error);

    const setSpan = (pi: number, si: number, patch: Partial<EditableSpan>) =>
        setParas((ps) => ps.map((p, i) => (i === pi ? p.map((s, j) => (j === si ? { ...s, ...patch } : s)) : p)));

    const save = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const v = await api.patch<ManuscriptVersion>(`/v1/manuscripts/${manuscriptId}`, {
                expected_version: expectedVersion,
                sections: [fromEditable(section, paras)],
                summary: summary.trim() || null,
            });
            onSaved(v);
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div data-testid="section-editor" className="flex flex-col gap-4 rounded-xl p-4 ring-2 ring-brand">
            <p className="text-xs text-tertiary">Editing against version {expectedVersion}. Sentences you change or add are recorded as yours and protected from regeneration.</p>
            {paras.map((p, pi) => (
                <fieldset key={pi} className="flex flex-col gap-3 rounded-lg bg-secondary p-3">
                    <legend className="text-xs font-medium text-tertiary">Paragraph {pi + 1}</legend>
                    {p.map((s, si) => (
                        <div key={si} className="flex flex-col gap-2 rounded-md bg-primary p-2 ring-1 ring-secondary">
                            <TextArea label={`Sentence ${pi + 1}.${si + 1}`} value={s.text} onChange={(v) => setSpan(pi, si, { text: v })} rows={2} />
                            <div className="grid gap-2 sm:grid-cols-3">
                                <NativeSelect
                                    size="sm"
                                    label="Kind"
                                    value={s.kind}
                                    onChange={(e) => setSpan(pi, si, { kind: e.target.value as EditableSpan["kind"] })}
                                    options={SPAN_KINDS.map((k) => ({ label: SPAN_KIND_LABEL[k], value: k }))}
                                />
                                <Input size="sm" label="Claim IDs" value={s.claim_ids} onChange={(v) => setSpan(pi, si, { claim_ids: v })} placeholder="CLM-0001" />
                                <Input size="sm" label="Result keys" value={s.result_keys} onChange={(v) => setSpan(pi, si, { result_keys: v })} placeholder="RES-001" />
                            </div>
                            <div>
                                <Button size="sm" color="tertiary-destructive" onClick={() => setParas((ps) => ps.map((x, i) => (i === pi ? x.filter((_, j) => j !== si) : x)))}>
                                    Remove sentence
                                </Button>
                            </div>
                        </div>
                    ))}
                    <div>
                        <Button size="sm" color="link-color" onClick={() => setParas((ps) => ps.map((x, i) => (i === pi ? [...x, blank()] : x)))}>
                            Add a sentence
                        </Button>
                    </div>
                </fieldset>
            ))}
            <div>
                <Button size="sm" color="link-color" onClick={() => setParas((ps) => [...ps, [blank()]])}>
                    Add a paragraph
                </Button>
            </div>
            <Input label="Change summary (optional)" value={summary} onChange={setSummary} />
            {conflict?.kind === "stale_version" ? (
                <div role="alert" data-testid="stale-version" className="flex flex-col gap-2 rounded-xl bg-warning-primary p-3 text-sm text-secondary">
                    <p>
                        {conflict.message}
                        {conflict.currentVersion != null && ` (current version ${conflict.currentVersion}).`} Your edits were not saved and nothing was overwritten.
                    </p>
                    <div>
                        <Button size="sm" color="secondary" onClick={onReload}>
                            Reload the current version
                        </Button>
                    </div>
                </div>
            ) : (
                <ErrorAlert error={error} />
            )}
            <div className="flex flex-wrap gap-2">
                <Button size="sm" isLoading={busy} onClick={save}>
                    Save as a new version
                </Button>
                <Button size="sm" color="secondary" onClick={onCancel}>
                    Cancel
                </Button>
            </div>
        </div>
    );
}
