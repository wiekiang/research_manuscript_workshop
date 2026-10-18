"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { NativeSelect } from "@/components/base/select/select-native";
import { Toggle } from "@/components/base/toggle/toggle";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { PdfPreview } from "@/components/research/pdf-preview";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { CompileRunEntry, TemplateEntry } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";

interface Props {
    projectId: string;
    templates: TemplateEntry[];
    currentVersionId: string;
    canEdit: boolean;
    onRequested: () => void;
}

/** Compile the committed version into the confirmed template inside the no-network sandbox. */
export function CompilePanel({ projectId, templates, currentVersionId, canEdit, onRequested }: Props) {
    const [anonymous, setAnonymous] = useState(true);
    const [bib, setBib] = useState("bibtex");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const confirmed = templates.find((t) => t.status === "confirmed");
    const runs: (CompileRunEntry & { template: string })[] = templates
        .flatMap((t) => t.compile_runs.filter((r) => r.kind === "manuscript").map((r) => ({ ...r, template: t.family ?? t.class_name ?? "template" })))
        .sort((a, b) => b.created_at.localeCompare(a.created_at));

    return (
        <Section
            title="Compile"
            description={
                confirmed
                    ? `Confirmed template: ${confirmed.family ?? confirmed.class_name} (${confirmed.mode}). Compilation runs in a sandbox with no network access.`
                    : "Confirm the official submission template first (LaTeX template workspace)."
            }
        >
            {canEdit && (
                <div className="flex flex-wrap items-end gap-4">
                    <Toggle isSelected={anonymous} onChange={setAnonymous} label="Anonymous (double-blind) build" />
                    <NativeSelect
                        size="sm"
                        className="w-40"
                        label="Bibliography"
                        value={bib}
                        onChange={(e) => setBib(e.target.value)}
                        options={(confirmed?.bib_modes.length ? confirmed.bib_modes : ["bibtex", "biber"]).map((m) => ({ label: m, value: m }))}
                    />
                    <Button
                        size="sm"
                        isLoading={busy}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(`/v1/projects/${projectId}/compile`, { anonymous, bib_mode: bib });
                                onRequested();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Compile current version
                    </Button>
                </div>
            )}
            <ErrorAlert error={error} />
            {runs.length === 0 && <p className="text-sm text-tertiary">No manuscript compiles yet.</p>}
            <ul className="flex flex-col gap-3">
                {runs.map((r) => (
                    <li key={r.id} data-testid="manuscript-compile-run" data-status={r.status} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={r.status} />
                            <span className="text-sm text-primary">
                                {r.template} · {r.options.anonymous ? "anonymous" : "with authors"} · {r.options.bib_mode}
                            </span>
                            {r.pages != null && <span className="text-xs text-tertiary">{r.pages} page(s)</span>}
                            <span className="text-xs text-tertiary">{formatDateTime(r.created_at)}</span>
                            <span className={r.manuscript_version_id === currentVersionId ? "text-xs text-success-primary" : "text-xs text-warning-primary"}>
                                {r.manuscript_version_id === currentVersionId ? "Current version" : "Older version"}
                            </span>
                        </div>
                        <ul className="grid gap-1 sm:grid-cols-2" aria-label="Compile checks">
                            {r.checks.map((c) => (
                                <li key={c.id} className="flex flex-wrap items-center gap-2 text-xs">
                                    <StatusBadge status={c.status} />
                                    <span className="text-secondary">{humanize(c.id)}</span>
                                    <span className="text-tertiary">{c.detail}</span>
                                </li>
                            ))}
                        </ul>
                        {r.errors.length > 0 && (
                            <ul className="list-disc pl-5 text-xs text-error-primary">
                                {r.errors.map((e) => (
                                    <li key={e}>{e}</li>
                                ))}
                            </ul>
                        )}
                        {r.pdf_artifact_id && <PdfPreview artifactId={r.pdf_artifact_id} title="Compiled manuscript PDF" />}
                    </li>
                ))}
            </ul>
        </Section>
    );
}
