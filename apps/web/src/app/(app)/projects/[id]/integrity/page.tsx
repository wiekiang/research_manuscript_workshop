"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TaskProgress } from "@/components/cfp/task-progress";
import { IntegrityReport } from "@/components/integrity/integrity-report";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { GatePanel } from "@/components/review/gate-panel";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { IntegrityView, Task } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { refusalHint } from "@/lib/review";

const ACTIVE = ["queued", "running", "failed_retryable"];

export default function IntegrityPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const view = useResource<IntegrityView>(pid ? `/v1/projects/${pid}/integrity` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const itTasks = (tasks.data?.items ?? []).filter((t) => t.kind === "integrity_check");
    const active = itTasks.some((t) => ACTIVE.includes(t.state));
    const reloadAll = () => void Promise.all([view.reload(), tasks.reload(), reload()]);

    useEffect(() => {
        reloadAll();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!active) return;
        const id = setInterval(reloadAll, 2000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    const reports = view.data?.items ?? [];
    const hint = refusalHint(error);

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Research integrity"
                description="Deterministic cross-stage checks of the current manuscript version: references, unsupported claims, result wording against assurance levels, provenance, data leakage, text overlap with stored sources, figures, licences, ethics, protocol deviations and disclosures."
            >
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
                                        await api.post(`/v1/projects/${pid}/integrity`, {});
                                        reloadAll();
                                    } catch (err) {
                                        setError(err);
                                    } finally {
                                        setBusy(false);
                                    }
                                }}
                            >
                                Run integrity checks
                            </Button>
                        </div>
                        <ErrorAlert error={error} />
                        {hint && <p className="text-sm text-tertiary">{hint}</p>}
                    </div>
                )}
                {view.isLoading && !view.data && <Loading label="Loading integrity reports" />}
                <ErrorAlert error={view.error} />
                {view.data && reports.length === 0 && (
                    <p data-testid="integrity-empty" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        No integrity report yet. The checks run on a complete manuscript, from scientific review onwards.
                    </p>
                )}
            </Section>

            <TaskProgress tasks={itTasks} title="Integrity tasks" onChanged={reloadAll} />

            {reports[0] && view.data && (
                <Section title={`Report for manuscript version ${reports[0].manuscript_version}`}>
                    <IntegrityReport report={reports[0]} declaration={view.data.decision_declaration} canEdit={canEdit} onChanged={reloadAll} />
                </Section>
            )}
            {reports.length > 1 && (
                <Section title="Earlier reports">
                    <ul className="flex flex-col gap-1 text-sm text-secondary">
                        {reports.slice(1).map((r) => (
                            <li key={r.id}>
                                Version {r.manuscript_version} · {formatDateTime(r.created_at)} · {r.summary.passed ? "no blocking problem found" : `${r.summary.failed.length} failed, ${r.summary.awaiting_decision.length} awaiting decision`}
                            </li>
                        ))}
                    </ul>
                </Section>
            )}

            <Section title="Compliance and integrity gate" description="Evaluated by the server before final approval.">
                <GatePanel project={project} fromState="COMPLIANCE_REVIEW" toState="FINAL_APPROVAL" gateIds={["compliance.checked", "integrity.checked", "readiness.pre_approval"]} onAdvanced={reloadAll} />
            </Section>
        </div>
    );
}
