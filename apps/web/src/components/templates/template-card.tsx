"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { Toggle } from "@/components/base/toggle/toggle";
import { ErrorAlert } from "@/components/research/error-alert";
import { Field } from "@/components/research/page-header";
import { PdfPreview } from "@/components/research/pdf-preview";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { CompileRunEntry, TemplateEntry } from "@/lib/api/types";
import { formatDateTime, humanize, shortHash } from "@/lib/format";
import { TEMPLATE_STATUS_TEXT, confirmBlockReason, templateLabel } from "./template-status";

const CHECK_LABEL: Record<string, string> = {
    "compile.success": "Compiles to PDF",
    "template.protected_unchanged": "Protected template files unchanged",
    "compile.shell_escape_disabled": "Shell escape disabled, no network",
    "citations.resolved": "Citations resolved",
    "figures.render": "Figures packaged and rendered",
    "anonymization.no_identity_leak": "No identifying content (text, metadata, sources, file names)",
    "anonymization.visual_inspection": "Visual anonymization review",
    "length.page_limit": "Page limit",
    "abstract.word_limit": "Abstract word limit",
    "template.supported": "Template supported",
};

function optionsLabel(o: CompileRunEntry["options"]): string {
    return [o.mode === "camera_ready" ? "Camera-ready" : "Submission", o.anonymous ? "double-blind" : "identified", o.bib_mode === "biber" ? "Biber" : "BibTeX"].join(" · ");
}

function CompileRun({ run }: { run: CompileRunEntry }) {
    return (
        <li data-testid="compile-run" data-status={run.status} className="flex flex-col gap-3 rounded-xl bg-secondary_subtle p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-primary">{optionsLabel(run.options)}</span>
                <StatusBadge status={run.status} />
                {run.freshness === "stale" && <StatusBadge status="stale" />}
                {run.pages !== null && <span className="text-xs text-tertiary">{run.pages} page{run.pages === 1 ? "" : "s"}</span>}
                <span className="text-xs text-tertiary">{formatDateTime(run.created_at)}</span>
                <span className="text-xs text-tertiary">· sample content, not a manuscript</span>
            </div>
            <ul className="flex flex-col gap-1" aria-label="Machine checks">
                {run.checks.map((c) => (
                    <li key={c.id} className="flex flex-wrap items-start gap-2 text-sm">
                        <StatusBadge status={c.status} />
                        <span className="font-medium text-secondary">{CHECK_LABEL[c.id] ?? c.id}</span>
                        <span className="text-xs text-tertiary">{c.detail}</span>
                    </li>
                ))}
            </ul>
            {run.errors.length > 0 && (
                <details className="text-xs">
                    <summary className="cursor-pointer text-error-primary">Compiler diagnostics ({run.errors.length})</summary>
                    <pre className="mt-2 overflow-x-auto rounded bg-primary p-2 whitespace-pre-wrap text-secondary ring-1 ring-secondary">{run.errors.join("\n")}</pre>
                </details>
            )}
            <div className="flex flex-wrap gap-3">
                {run.report_artifact_id && <ArtifactLink artifactId={run.report_artifact_id} label="Compile report" />}
                {run.log_artifact_id && <ArtifactLink artifactId={run.log_artifact_id} label="Log" />}
                {run.source_bundle_artifact_id && <ArtifactLink artifactId={run.source_bundle_artifact_id} label="Generated source" />}
            </div>
            {run.pdf_artifact_id && <PdfPreview artifactId={run.pdf_artifact_id} title={`Sample PDF: ${optionsLabel(run.options)}`} />}
        </li>
    );
}

function SampleCompileForm({ projectId, t, onQueued }: { projectId: string; t: TemplateEntry; onQueued: () => void }) {
    const [anonymous, setAnonymous] = useState(false);
    const [bib, setBib] = useState(t.bib_modes[0] ?? "bibtex");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <div className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
            <p className="text-sm font-semibold text-secondary">Run another sample compile</p>
            <div className="flex flex-wrap items-end gap-4">
                <Toggle isSelected={anonymous} onChange={setAnonymous} label="Double-blind build" />
                <NativeSelect label="Bibliography mode" value={bib} onChange={(e) => setBib(e.target.value)} options={t.bib_modes.map((m) => ({ label: m === "biber" ? "Biber (biblatex)" : "BibTeX", value: m }))} className="max-w-xs" />
                <Button
                    color="secondary"
                    isLoading={busy}
                    onClick={async () => {
                        setBusy(true);
                        setError(undefined);
                        try {
                            await api.post(`/v1/projects/${projectId}/templates/${t.id}/compile-sample`, { anonymous, bib_mode: bib });
                            onQueued();
                        } catch (err) {
                            setError(err);
                        } finally {
                            setBusy(false);
                        }
                    }}
                >
                    Compile sample
                </Button>
            </div>
            <ErrorAlert error={error} />
        </div>
    );
}

function ConfirmTemplate({ projectId, t, onConfirmed }: { projectId: string; t: TemplateEntry; onConfirmed: () => void }) {
    const [accepted, setAccepted] = useState(false);
    const [overleaf, setOverleaf] = useState(t.overleaf_export_allowed ?? false);
    const [license, setLicense] = useState(t.license_note ?? "");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const blocked = confirmBlockReason(t);
    if (t.status === "confirmed") return null;
    return (
        <section aria-labelledby={`confirm-${t.id}`} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-utility-amber-200">
            <h4 id={`confirm-${t.id}`} className="text-sm font-semibold text-primary">
                Confirm the template source and mode
            </h4>
            <blockquote className="border-l-2 border-brand pl-3 text-sm text-secondary">{t.declaration}</blockquote>
            {blocked && (
                <p role="status" className="text-sm text-tertiary">
                    {blocked}
                </p>
            )}
            <Input label="License or reuse note" value={license} onChange={setLicense} isDisabled={!!blocked} />
            <Toggle isSelected={overleaf} onChange={setOverleaf} isDisabled={!!blocked} label="The template's terms allow an Overleaf-compatible source export" />
            <Checkbox isSelected={accepted} onChange={setAccepted} isDisabled={!!blocked} label="I have read this declaration and it is true for this template" />
            <ErrorAlert error={error} />
            <div>
                <Button
                    isDisabled={!!blocked || !accepted}
                    isLoading={busy}
                    onClick={async () => {
                        setBusy(true);
                        setError(undefined);
                        try {
                            await api.post(`/v1/projects/${projectId}/templates/${t.id}/confirm`, { declaration_accepted: true, overleaf_export_allowed: overleaf, license_note: license || null });
                            onConfirmed();
                        } catch (err) {
                            setError(err);
                        } finally {
                            setBusy(false);
                        }
                    }}
                >
                    Confirm template
                </Button>
            </div>
        </section>
    );
}

export function TemplateCard({ projectId, t, isOwner, onChanged }: { projectId: string; t: TemplateEntry; isOwner: boolean; onChanged: () => void }) {
    const label = templateLabel(t);
    const protectedFiles = t.files.filter((f) => f.protected);
    const cfp = t.cfp_consistency ?? {};
    return (
        <article data-testid="template-card" data-status={t.status} aria-labelledby={`tpl-${t.id}`} className="flex flex-col gap-5 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <header className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <h3 id={`tpl-${t.id}`} className="font-display text-lg font-semibold text-primary">
                        {t.class_name ? `${t.class_name} template` : "Template"}{" "}
                        <span className="text-sm font-normal text-tertiary">({t.mode === "camera_ready" ? "camera-ready" : "initial submission"})</span>
                    </h3>
                    <StatusBadge status={t.status === "confirmed" ? "confirmed" : t.status} label={t.status === "confirmed" ? "Confirmed by you" : undefined} />
                    <StatusBadge status={label.tone === "ok" ? "complete" : "blocked"} label={label.text} />
                </div>
                <p className="text-sm text-tertiary">{TEMPLATE_STATUS_TEXT[t.status] ?? humanize(t.status)}</p>
            </header>
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Field label="Origin">{t.origin === "official_link" ? "Retrieved from the official link" : "Supplied by a researcher"}</Field>
                <Field label="Source URL">
                    <span className="break-all">{t.source_url ?? "—"}</span>
                </Field>
                <Field label="Retrieved">{t.retrieved_at ? formatDateTime(t.retrieved_at) : "—"}</Field>
                <Field label="Family / class">{t.family ? `${t.family} / ${t.class_name ?? "—"}` : "—"}</Field>
                <Field label="Bibliography modes">{t.bib_modes.length ? t.bib_modes.map((m) => (m === "biber" ? "Biber" : "BibTeX")).join(", ") : "—"}</Field>
                <Field label="Archive">{t.archive_artifact_id ? <ArtifactLink artifactId={t.archive_artifact_id} hash={t.archive_hash} label="Template ZIP" /> : shortHash(t.archive_hash ?? "") || "—"}</Field>
                <Field label="License note">{t.license_note ?? "Not recorded"}</Field>
                <Field label="Overleaf export">{t.overleaf_export_allowed === null ? "Not confirmed" : t.overleaf_export_allowed ? "Allowed by the template's terms" : "Not allowed"}</Field>
                {t.declared_origin && <Field label="Declared origin">{t.declared_origin}</Field>}
            </dl>
            {t.unsupported_reasons.length > 0 && (
                <div role="alert" className="rounded-xl bg-error-primary p-4 text-sm text-error-primary">
                    <p className="font-semibold">Why this template cannot be used for a submission-ready package</p>
                    <ul className="list-disc pl-5">
                        {t.unsupported_reasons.map((r) => (
                            <li key={r}>{r}</li>
                        ))}
                    </ul>
                </div>
            )}
            {t.issues.length > 0 && (
                <div className="flex flex-col gap-1">
                    <p className="text-sm font-semibold text-secondary">Analysis notes</p>
                    <ul className="flex flex-col gap-1 text-sm">
                        {t.issues.map((i, n) => (
                            <li key={n} className="flex flex-wrap gap-2">
                                <StatusBadge status={i.severity === "error" ? "failed" : i.severity === "warning" ? "warning" : "queued"} label={humanize(i.severity)} />
                                <span className="text-secondary">{i.message}</span>
                                {i.path && <code className="text-xs text-tertiary">{i.path}</code>}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {cfp.status && (
                <div className="flex flex-col gap-1 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-secondary">Matches the CFP's template rule</span>
                        <StatusBadge status={cfp.status} />
                    </div>
                    {cfp.detail && <p className="text-tertiary">{cfp.detail}</p>}
                    {cfp.cfp_value && (
                        <p className="text-tertiary">
                            CFP rule value: {cfp.cfp_value}; template family: {cfp.template_family ?? "unknown"}
                        </p>
                    )}
                    {cfp.quote && <blockquote className="border-l-2 border-brand pl-3 text-secondary italic">“{cfp.quote}”</blockquote>}
                </div>
            )}
            {protectedFiles.length > 0 && (
                <details>
                    <summary className="cursor-pointer text-sm font-semibold text-secondary">Protected template files ({protectedFiles.length}) — never modified</summary>
                    <ul className="mt-2 flex flex-col gap-1 text-xs" data-testid="protected-files">
                        {protectedFiles.map((f) => (
                            <li key={f.path} className="flex flex-wrap gap-2">
                                <code className="text-secondary">{f.path}</code>
                                <span className="text-tertiary">{humanize(f.role)}</span>
                                <span className="text-tertiary">sha256 {shortHash(f.sha256)}</span>
                                <span className="font-medium text-success-primary">Protected</span>
                            </li>
                        ))}
                    </ul>
                </details>
            )}
            <section aria-label="Compile runs" className="flex flex-col gap-3">
                <h4 className="text-sm font-semibold text-secondary">Sandboxed compile runs</h4>
                {t.compile_runs.length === 0 && <p className="text-sm text-tertiary">{t.status === "analyzing" ? "Compiles start after analysis." : "No compile runs."}</p>}
                <ul className="flex flex-col gap-3">
                    {t.compile_runs.map((r) => (
                        <CompileRun key={r.id} run={r} />
                    ))}
                </ul>
            </section>
            {isOwner && t.supported && t.status !== "analyzing" && <SampleCompileForm projectId={projectId} t={t} onQueued={onChanged} />}
            {isOwner && <ConfirmTemplate projectId={projectId} t={t} onConfirmed={onChanged} />}
        </article>
    );
}
