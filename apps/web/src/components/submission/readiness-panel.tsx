"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { ArtifactLink } from "@/components/research/provenance-link";
import { ErrorAlert } from "@/components/research/error-alert";
import { Field } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { GateResult, ReadinessAssessmentEntry, ReadinessView } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { STAGE_LABEL } from "@/lib/submission";
import { ReadinessStepper } from "./readiness-stepper";

export function GateList({ gates }: { gates: GateResult[] }) {
    return (
        <ul className="flex flex-col gap-2" data-testid="readiness-gates">
            {gates.map((g) => (
                <li key={g.gate_id} data-testid="readiness-gate" data-gate={g.gate_id} data-passed={g.passed} className="flex flex-col gap-1">
                    <p className="flex items-center gap-2 text-sm">
                        <StatusBadge status={g.passed ? "passed" : "blocked"} label={g.passed ? "Satisfied" : "Not satisfied"} />
                        <span className="font-mono text-secondary">{g.gate_id}</span>
                    </p>
                    {g.reasons.length > 0 && (
                        <ul className="list-disc pl-5 text-sm text-secondary">
                            {g.reasons.map((r) => (
                                <li key={r}>{r}</li>
                            ))}
                        </ul>
                    )}
                </li>
            ))}
        </ul>
    );
}

export function AssessmentCard({ a }: { a: ReadinessAssessmentEntry }) {
    return (
        <article data-testid="readiness-assessment" className="flex flex-col gap-3 rounded-xl border border-secondary p-4">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-primary">{STAGE_LABEL[a.stage] ?? a.stage}</span>
                <span className="text-xs text-tertiary">{formatDateTime(a.created_at)}</span>
                <ArtifactLink artifactId={a.artifact_id} label="Assessment artifact" />
            </div>
            <dl className="grid gap-3 sm:grid-cols-2">
                <Field label="Assessor">{a.assessor}</Field>
                <Field label="Assessor version">{a.assessor_version}</Field>
            </dl>
            <ul className="flex flex-col gap-1 text-sm">
                {a.checks.map((c) => (
                    <li key={c.gate} className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={c.passed ? "passed" : "blocked"} label={c.passed ? "Passed" : "Not passed"} />
                        <span className="font-mono text-secondary">{c.gate}</span>
                        {c.reasons.length > 0 && <span className="text-tertiary">{c.reasons.join("; ")}</span>}
                    </li>
                ))}
            </ul>
            {a.manual_checks.length > 0 && (
                <div className="flex flex-col gap-1">
                    <p className="text-xs font-semibold text-secondary">Manual checks recorded with this assessment</p>
                    <ul className="list-disc pl-5 text-sm text-secondary">
                        {a.manual_checks.map((m) => (
                            <li key={m.id}>
                                <span className="font-mono">{m.id}</span>: {m.detail}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {a.limitations.length > 0 && (
                <div className="flex flex-col gap-1">
                    <p className="text-xs font-semibold text-secondary">Remaining limitations</p>
                    <ul className="list-disc pl-5 text-sm text-secondary">
                        {a.limitations.map((l) => (
                            <li key={l}>{l}</li>
                        ))}
                    </ul>
                </div>
            )}
        </article>
    );
}

/**
 * Live readiness stage (evaluated by the server now) and the versioned assessments that were recorded. Manual checks
 * from the latest assessment stay visible even when every automated gate passes.
 */
export function ReadinessPanel({ view, projectId, canEdit, onChanged }: { view: ReadinessView; projectId: string; canEdit: boolean; onChanged: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const latest = view.items[0];
    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
                <p className="text-sm text-secondary">
                    Current stage (evaluated now): <span data-testid="readiness-current-stage" data-stage={view.current_stage} className="font-semibold text-primary">{STAGE_LABEL[view.current_stage] ?? view.current_stage}</span>
                </p>
                <ReadinessStepper stage={view.current_stage} />
                <p data-testid="readiness-notice" className="rounded-xl bg-secondary p-3 text-sm text-secondary">
                    {view.notice}
                </p>
            </div>
            <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold text-primary">Gate results</h3>
                <GateList gates={Object.values(view.gates)} />
            </div>
            <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold text-primary">Outstanding manual checks</h3>
                {latest && latest.manual_checks.length > 0 ? (
                    <ul data-testid="manual-checks" className="list-disc pl-5 text-sm text-secondary">
                        {latest.manual_checks.map((m) => (
                            <li key={m.id}>
                                <span className="font-mono">{m.id}</span>: {m.detail}
                                {m.source && <span className="text-tertiary"> ({m.source})</span>}
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p data-testid="manual-checks-none" className="text-sm text-tertiary">
                        {latest ? "The latest assessment recorded no manual checks." : "No readiness assessment has been recorded yet, so manual checks are not listed yet."}
                    </p>
                )}
            </div>
            {canEdit && (
                <div className="flex flex-col gap-2">
                    <div>
                        <Button
                            size="sm"
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    await api.post(`/v1/projects/${projectId}/readiness`, {});
                                    onChanged();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Record readiness assessment
                        </Button>
                    </div>
                    <p className="text-xs text-tertiary">Records a versioned assessment of the current manuscript version. H4 requires the pre-approval assessment (stage “compliance checked”).</p>
                    <ErrorAlert error={error} />
                </div>
            )}
            <div className="flex flex-col gap-3">
                <h3 className="text-sm font-semibold text-primary">Assessment history</h3>
                {view.items.length === 0 ? (
                    <p className="text-sm text-tertiary">No assessments recorded.</p>
                ) : (
                    view.items.map((a) => <AssessmentCard key={a.id} a={a} />)
                )}
            </div>
        </div>
    );
}
