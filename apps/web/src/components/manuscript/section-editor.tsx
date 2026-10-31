"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { IssueList } from "@/components/manuscript/span-view";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { ContentSection, ManuscriptVersion, TableIssue } from "@/lib/api/types";
import { type EditableSpan, type EditableTable, SPAN_KINDS, SPAN_KIND_LABEL, fromEditable, interpretConflict, toEditable, toEditableTables } from "@/lib/manuscript";

interface Props {
    manuscriptId: string;
    section: ContentSection;
    expectedVersion: number;
    /** Table check issues recorded on the committed version for this section (located by table_index). */
    tableIssues?: TableIssue[];
    onSaved: (v: ManuscriptVersion) => void;
    onCancel: () => void;
    onReload: () => void;
}

const blank = (): EditableSpan => ({ span_id: "", text: "", kind: "framing", claim_ids: "", result_keys: "" });

/**
 * Edit one section sentence by sentence. Saving sends the expected version; if the manuscript changed meanwhile the
 * API refuses (409) and nothing is overwritten. Changed or new sentences become human-authored and protected.
 */
export function SectionEditor({ manuscriptId, section, expectedVersion, tableIssues = [], onSaved, onCancel, onReload }: Props) {
    const [paras, setParas] = useState<EditableSpan[][]>(() => {
        const p = toEditable(section);
        return p.length ? p : [[blank()]];
    });
    // orig is the table's index in the committed version, which is how the server locates table check issues.
    const [tables, setTables] = useState<(EditableTable & { orig: number })[]>(() => toEditableTables(section).map((t, i) => ({ ...t, orig: i })));
    const [summary, setSummary] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const conflict = interpretConflict(error);

    const setSpan = (pi: number, si: number, patch: Partial<EditableSpan>) =>
        setParas((ps) => ps.map((p, i) => (i === pi ? p.map((s, j) => (j === si ? { ...s, ...patch } : s)) : p)));
    const setTable = (ti: number, patch: Partial<EditableTable>) => setTables((ts) => ts.map((t, i) => (i === ti ? { ...t, ...patch } : t)));

    const save = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const v = await api.patch<ManuscriptVersion>(`/v1/manuscripts/${manuscriptId}`, {
                expected_version: expectedVersion,
                sections: [fromEditable(section, paras, tables)],
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
            <fieldset data-testid="tables-editor" className="flex flex-col gap-3 rounded-lg bg-secondary p-3">
                <legend className="text-xs font-medium text-tertiary">Result tables</legend>
                <p className="text-xs text-tertiary">A table is rendered from the committed results it names, never from prose; a key that is not a committed result blocks completion.</p>
                {tables.length === 0 && <p className="text-xs text-tertiary">This section has no tables.</p>}
                {tables.map((t, ti) => {
                    // Issues are located by the table's index in the committed version, so a table added here
                    // (orig -1, not yet committed) never adopts another table's issues.
                    const issues = t.orig < 0 ? [] : tableIssues.filter((i) => i.table_index === t.orig);
                    return (
                        <div key={ti} data-testid="table-editor" data-status={issues.some((i) => i.severity === "blocker") ? "blocked" : issues.length ? "issues" : "ok"} className="flex flex-col gap-2 rounded-md bg-primary p-2 ring-1 ring-secondary">
                            <div className="grid gap-2 sm:grid-cols-2">
                                <Input size="sm" label={`Table ${ti + 1} caption`} value={t.caption} onChange={(v) => setTable(ti, { caption: v })} />
                                <Input size="sm" label="Result keys" value={t.result_keys} onChange={(v) => setTable(ti, { result_keys: v })} placeholder="RES-001" />
                            </div>
                            <IssueList issues={issues} label="Table check issues" />
                            <div>
                                <Button size="sm" color="tertiary-destructive" onClick={() => setTables((ts) => ts.filter((_, j) => j !== ti))}>
                                    Remove table
                                </Button>
                            </div>
                        </div>
                    );
                })}
                <div>
                    <Button size="sm" color="link-color" onClick={() => setTables((ts) => [...ts, { caption: "", result_keys: "", orig: -1 }])}>
                        Add a table
                    </Button>
                </div>
            </fieldset>
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
