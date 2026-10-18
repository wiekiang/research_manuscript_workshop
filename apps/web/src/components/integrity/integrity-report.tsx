"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { DecisionDialog } from "@/components/review/decision-dialog";
import type { IntegrityCheckEntry, IntegrityReportEntry } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { checkStatusKey } from "@/lib/review";

/**
 * ResearchIntegrityReport: each check with its evidence, scope and limitations. Failed checks cannot be waived;
 * warnings and manual checks need a signed human decision. The disclaimer is shown verbatim.
 */
export function IntegrityReport({ report, declaration, canEdit, onChanged }: { report: IntegrityReportEntry; declaration: string; canEdit: boolean; onChanged: () => void }) {
    const [deciding, setDeciding] = useState<IntegrityCheckEntry | null>(null);
    return (
        <div className="flex flex-col gap-4" data-testid="integrity-report" data-passed={report.summary.passed}>
            <p data-testid="integrity-disclaimer" className="rounded-xl bg-secondary p-4 text-sm text-secondary">
                {report.summary.disclaimer}
            </p>
            <div className="flex flex-wrap items-center gap-3 text-sm text-secondary">
                <StatusBadge status={report.status === "complete" ? (report.summary.passed ? "passed" : "blocked") : "running"} label={report.status !== "complete" ? "Running" : report.summary.passed ? "No blocking problem found" : "Blocking problems or decisions outstanding"} />
                <span>
                    Manuscript version {report.manuscript_version} · {report.engine} · {formatDateTime(report.created_at)}
                </span>
                {report.artifact_id && <ArtifactLink artifactId={report.artifact_id} label="Report artifact" />}
            </div>
            {report.summary.failed.length > 0 && (
                <p className="text-sm text-error-primary">Failed or not performed (must be fixed, cannot be waived): {report.summary.failed.join(", ")}</p>
            )}
            {report.summary.awaiting_decision.length > 0 && <p className="text-sm text-secondary">Awaiting your signed decision: {report.summary.awaiting_decision.join(", ")}</p>}
            <ul className="flex flex-col gap-2">
                {report.checks.map((c) => (
                    <li key={c.id} data-testid="integrity-check" data-check={c.id} data-status={c.status} className="flex flex-col gap-1.5 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-primary">{c.title}</span>
                            <StatusBadge status={checkStatusKey(c.status)} />
                            <span className="font-mono text-xs text-tertiary">{c.id}</span>
                        </div>
                        <p className="text-sm text-secondary">{c.detail}</p>
                        <p className="text-xs text-tertiary">Scope: {c.scope}</p>
                        {c.limitations && <p className="text-xs text-tertiary">Limitations: {c.limitations}</p>}
                        {Object.keys(c.evidence ?? {}).length > 0 && (
                            <details>
                                <summary className="cursor-pointer text-xs text-tertiary">Evidence</summary>
                                <pre className="mt-1 overflow-auto rounded bg-secondary p-2 text-xs whitespace-pre-wrap text-secondary">{JSON.stringify(c.evidence, null, 2)}</pre>
                            </details>
                        )}
                        {c.decision && (
                            <p className="text-xs text-tertiary" data-testid="integrity-decision">
                                Signed decision: {c.decision.decision.replace(/_/g, " ")} — {c.decision.rationale} · {formatDateTime(c.decision.at)}
                            </p>
                        )}
                        {canEdit && c.requires_decision && !c.decision && (
                            <div>
                                <Button size="sm" color="secondary" onClick={() => setDeciding(c)}>
                                    Record signed decision
                                </Button>
                            </div>
                        )}
                    </li>
                ))}
            </ul>
            {deciding && (
                <DecisionDialog
                    isOpen
                    onOpenChange={(o) => !o && setDeciding(null)}
                    path={`/v1/integrity-reports/${report.id}/checks/${encodeURIComponent(deciding.id)}/decide`}
                    checkId={deciding.id}
                    detail={deciding.detail}
                    declaration={declaration}
                    onDone={onChanged}
                />
            )}
        </div>
    );
}
