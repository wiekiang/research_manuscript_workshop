"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/base/buttons/button";
import { ErrorAlert } from "@/components/research/error-alert";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { TaskActions } from "@/components/research/task-actions";
import { api } from "@/lib/api/client";
import type { ExperimentRunEntry, PromoteResult, Recomputation, Reproduction, Task } from "@/lib/api/types";
import { canPromote, canRerun, experimentHint, FAILED_STATES, metricsAreFindings, recomputationKey } from "@/lib/experiments";
import { formatDateTime } from "@/lib/format";

function num(v: number | null | undefined): string {
    return v === null || v === undefined ? "—" : String(v);
}

/** First run vs reproduction rerun, metric by metric, against the plan's preset tolerance. */
export function ReproductionTable({ reproduction }: { reproduction: Reproduction }) {
    return (
        <div data-testid="reproduction" data-match={reproduction.match} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={reproduction.match ? "reproduction_match" : "reproduction_mismatch"} />
                <span className="text-xs text-tertiary">Tolerance (absolute): {reproduction.tolerance}</span>
            </div>
            <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                    <thead>
                        <tr className="text-xs text-tertiary">
                            <th className="py-1 pr-4 font-medium">Metric</th>
                            <th className="py-1 pr-4 font-medium">First run</th>
                            <th className="py-1 pr-4 font-medium">Rerun</th>
                            <th className="py-1 pr-4 font-medium">Difference</th>
                            <th className="py-1 font-medium">Within tolerance</th>
                        </tr>
                    </thead>
                    <tbody>
                        {reproduction.rows.map((r) => (
                            <tr key={r.metric} data-testid="reproduction-row" className="border-t border-secondary">
                                <td className="py-1 pr-4 font-mono text-xs text-primary">{r.metric}</td>
                                <td className="py-1 pr-4 font-mono text-xs">{num(r.first)}</td>
                                <td className="py-1 pr-4 font-mono text-xs">{num(r.rerun)}</td>
                                <td className="py-1 pr-4 font-mono text-xs">{num(r.difference)}</td>
                                <td className="py-1 text-xs">{r.within_tolerance ? "Yes" : "No"}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export function RecomputationView({ recomputation }: { recomputation: Recomputation }) {
    return (
        <div data-testid="recomputation" data-status={recomputation.status} className="flex flex-col gap-1 text-sm">
            <p className="text-xs text-tertiary">Validator {recomputation.validator}</p>
            {recomputation.detail && <p className="text-secondary">{recomputation.detail}</p>}
            {recomputation.checks.length > 0 && (
                <ul className="flex flex-col gap-1">
                    {recomputation.checks.map((c) => (
                        <li key={c.id} className="flex flex-wrap items-center gap-2 text-xs">
                            <StatusBadge status={c.status} />
                            <span className="font-mono text-tertiary">{c.id}</span>
                            <span className="text-secondary">{c.detail}</span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

interface Props {
    projectId: string;
    run: ExperimentRunEntry;
    task?: Task;
    canEdit: boolean;
    onChanged: () => void;
    onRerun?: (run: ExperimentRunEntry) => void;
    rerunBusy?: boolean;
}

/**
 * One sandboxed run. A failed, timed-out or sandbox-unavailable run is shown as such with its diagnostics; its values
 * are never presented as results, and it is never promotable.
 */
export function RunCard({ projectId, run, task, canEdit, onChanged, onRerun, rerunBusy }: Props) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [promoted, setPromoted] = useState<PromoteResult>();
    const failed = FAILED_STATES.includes(run.status);
    const findings = metricsAreFindings(run);
    const hint = experimentHint(error);

    const promote = async () => {
        setBusy(true);
        setError(undefined);
        try {
            setPromoted(await api.post<PromoteResult>(`/v1/experiment-runs/${run.id}/promote`, {}));
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <article data-testid="experiment-run" data-status={run.status} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={`run_${run.status}`} size="md" />
                {run.rerun_of && <span className="text-xs text-secondary">Reproduction rerun of run {run.rerun_of.slice(0, 8)}</span>}
                <span className="font-mono text-xs text-tertiary">Run {run.id.slice(0, 8)}</span>
                <span className="text-xs text-tertiary">{formatDateTime(run.created_at)}</span>
                {run.result_manifest_id && <StatusBadge status="succeeded" label="Registered as a result" />}
            </div>

            {failed && (
                <div data-testid="run-failure" className="rounded-lg bg-error-primary p-3 text-sm">
                    <p className="font-medium text-error-primary">This run did not produce a usable result and cannot become a finding.</p>
                    {run.failure_reason && <p className="text-secondary">{run.failure_reason}</p>}
                </div>
            )}

            <dl className="grid gap-2 text-sm sm:grid-cols-3">
                <div>
                    <dt className="text-xs text-tertiary">Exit code</dt>
                    <dd className="font-mono text-xs text-primary">{num(run.exit_code)}</dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Duration</dt>
                    <dd className="font-mono text-xs text-primary">{run.duration_s === null ? "—" : `${run.duration_s.toFixed(2)} s`}</dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Independent recomputation</dt>
                    <dd>
                        <StatusBadge status={recomputationKey(run)} />
                    </dd>
                </div>
            </dl>

            {!failed && run.reported_metrics && (
                <div data-testid="reported-metrics" data-findings={findings} className="flex flex-col gap-1">
                    <p className="text-xs text-tertiary">
                        {findings
                            ? "Reported by the run and independently recomputed from its raw outputs"
                            : "Reported by the run itself — not a finding until the validator recomputes it from the raw outputs"}
                    </p>
                    <ul className="flex flex-wrap gap-3 font-mono text-xs text-primary">
                        {Object.entries(run.reported_metrics).map(([k, v]) => (
                            <li key={k}>
                                {k} = {v}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {run.status === "succeeded" && run.recomputation && <RecomputationView recomputation={run.recomputation} />}
            {run.reproduction && <ReproductionTable reproduction={run.reproduction} />}

            <div className="flex flex-wrap gap-3">
                {run.run_manifest_artifact_id && <ArtifactLink artifactId={run.run_manifest_artifact_id} label="Run manifest" />}
                {run.raw_output_artifact_id && <ArtifactLink artifactId={run.raw_output_artifact_id} label="Raw outputs" />}
                {run.predictions_artifact_id && <ArtifactLink artifactId={run.predictions_artifact_id} label="Predictions" />}
                {run.log_artifact_id && <ArtifactLink artifactId={run.log_artifact_id} label="Log" />}
                {run.recomputation_artifact_id && <ArtifactLink artifactId={run.recomputation_artifact_id} label="Recomputation report" />}
            </div>

            {task && <TaskActions projectId={projectId} task={task} onChanged={onChanged} canEdit={canEdit} />}

            {canEdit && (
                <div className="flex flex-wrap gap-2">
                    {canPromote(run) && (
                        <Button size="sm" isLoading={busy} onClick={promote}>
                            Register as a result
                        </Button>
                    )}
                    {canRerun(run) && onRerun && !run.rerun_of && (
                        <Button size="sm" color="secondary" isLoading={rerunBusy} onClick={() => onRerun(run)}>
                            Start reproduction rerun
                        </Button>
                    )}
                </div>
            )}
            {promoted && (
                <p data-testid="promoted" className="text-sm text-secondary">
                    Registered as {promoted.result_key} ({promoted.rerun_documented ? "a matching reproduction rerun is documented" : "no reproduction rerun documented yet"}).
                    The assurance assessment runs next.{" "}
                    <Link href={`/projects/${projectId}/contributions`} className="text-brand-secondary underline">
                        View results
                    </Link>
                </p>
            )}
            <ErrorAlert error={error} />
            {hint && <p className="text-sm text-tertiary">{hint}</p>}
        </article>
    );
}
