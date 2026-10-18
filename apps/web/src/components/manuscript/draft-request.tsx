"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { humanize } from "@/lib/format";

interface Props {
    projectId: string;
    /** Section keys of the current manuscript (empty before the first draft: all planned sections are drafted). */
    sections: { key: string; heading: string }[];
    canEdit: boolean;
    onRequested: (r: { mode: string; base_version: number }) => void;
}

/**
 * Request an evidence-grounded draft. The API freezes a brief (verified claims, committed results with wording
 * limits, the H3 matrix and gap assessment) and the current version; refusals are shown exactly as returned.
 */
export function DraftRequest({ projectId, sections, canEdit, onRequested }: Props) {
    const [selected, setSelected] = useState<string[]>([]);
    const [instructions, setInstructions] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [last, setLast] = useState<{ mode: string; base_version: number }>();

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const r = await api.post<{ mode: string; base_version: number }>(
                `/v1/projects/${projectId}/drafts`,
                { sections: selected.length ? selected : null, instructions: instructions.trim() || null },
                newIdempotencyKey("draft"),
            );
            setLast(r);
            onRequested(r);
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    if (!canEdit) return null;
    return (
        <Section title="Request a draft" description="Drafts cite only verified claims and committed results. You review every draft before it becomes a version.">
            {sections.length > 0 && (
                <fieldset className="flex flex-col gap-1">
                    <legend className="text-sm font-medium text-secondary">Sections (none selected = all)</legend>
                    <div className="grid gap-1 sm:grid-cols-4">
                        {sections.map((s) => (
                            <Checkbox key={s.key} isSelected={selected.includes(s.key)} onChange={(v) => setSelected((x) => (v ? [...x, s.key] : x.filter((y) => y !== s.key)))} label={s.heading || humanize(s.key)} />
                        ))}
                    </div>
                </fieldset>
            )}
            <TextArea label="Instructions for the writer (optional)" value={instructions} onChange={setInstructions} rows={2} />
            <ErrorAlert error={error} />
            {last && (
                <p className="text-sm text-tertiary" role="status">
                    Draft requested against version {last.base_version} in {last.mode === "proposal" ? "research-proposal mode (no H3: observed results cannot be reported)" : "paper mode"}.
                </p>
            )}
            <div>
                <Button size="sm" isLoading={busy} onClick={submit}>
                    Request draft
                </Button>
            </div>
        </Section>
    );
}
