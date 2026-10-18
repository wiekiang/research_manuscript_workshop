"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TaskProgress } from "@/components/cfp/task-progress";
import { OpportunityCard } from "@/components/opportunities/opportunity-card";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { DirectionApproval } from "@/components/method/direction-approval";
import { StudyTypeSelector } from "@/components/method/study-type-selector";
import { useResource } from "@/hooks/use-resource";
import { ApiError, api } from "@/lib/api/client";
import type { ApprovalsView, OpportunityList, StudyTypeTaxonomy, Task, WorkflowDefinitionView } from "@/lib/api/types";

export default function DirectionWorkspace() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const ops = useResource<OpportunityList>(pid ? `/v1/projects/${pid}/opportunities` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const wf = useResource<WorkflowDefinitionView>(pid ? `/v1/projects/${pid}/workflow-definition` : null);
    const tax = useResource<StudyTypeTaxonomy>(pid ? `/v1/projects/${pid}/study-types` : null);
    const approvals = useResource<ApprovalsView>(pid ? `/v1/projects/${pid}/approvals` : null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const oppTasks = (tasks.data?.items ?? []).filter((t) => t.kind === "opportunity_generation");
    const active = oppTasks.some((t) => ["queued", "running", "failed_retryable"].includes(t.state));
    const reloadAll = () => void Promise.all([ops.reload(), tasks.reload(), wf.reload(), approvals.reload()]);

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
    const isOwner = project.my_role === "owner";
    const canEdit = isOwner || project.my_role === "coauthor";
    const insufficient = error instanceof ApiError && error.code === "insufficient_literature";
    const h1Current = approvals.data?.items.find((a) => a.gate === "H1" && a.is_current);
    const lastResult = oppTasks[0]?.result as { status?: string; agent_problems?: string[] } | undefined;
    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Research direction proposals"
                description={ops.data?.note ?? "Proposals are advisory; the research direction is your decision."}
                actions={
                    isOwner && (
                        <Button
                            size="sm"
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    await api.post(`/v1/projects/${pid}/opportunities/generate`, {});
                                    reloadAll();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Propose research directions
                        </Button>
                    )
                }
            >
                <div className="flex flex-wrap items-center gap-3">
                    {ops.data && <StatusBadge status={ops.data.direction_state} />}
                    <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/direction/study-types`}>
                        Study types and venue categories explained
                    </a>
                </div>
                {insufficient ? (
                    <p role="alert" className="rounded-xl bg-warning-primary p-4 text-sm text-secondary">
                        Search for or add at least three papers in the{" "}
                        <a className="underline" href={`/projects/${pid}/literature`}>
                            literature workspace
                        </a>{" "}
                        before proposing research gaps. Gaps must be grounded in documented literature.
                    </p>
                ) : (
                    <ErrorAlert error={error} />
                )}
                <TaskProgress tasks={oppTasks} title="Proposal generation" />
                {lastResult?.status && lastResult.status.startsWith("not_performed") && (
                    <p className="text-sm text-warning-primary">The proposal agent did not run ({lastResult.status}). No proposals were invented.</p>
                )}
                {(lastResult?.agent_problems ?? []).length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-tertiary">
                        {(lastResult?.agent_problems ?? []).map((p) => (
                            <li key={p}>Validation: {p}</li>
                        ))}
                    </ul>
                )}
                {ops.isLoading && !ops.data && <Loading label="Loading proposals" />}
                <ErrorAlert error={ops.error} />
                {ops.data && ops.data.items.length === 0 && <p className="text-sm text-tertiary">No proposals yet.</p>}
                <div className="flex flex-col gap-6">
                    {(ops.data?.items ?? []).map((o) => (
                        <OpportunityCard key={o.id} projectId={pid} o={o} canEdit={canEdit} onChanged={reloadAll} />
                    ))}
                </div>
            </Section>
            <StudyTypeSelector
                key={wf.data?.instance?.id ?? "none"}
                projectId={pid}
                instance={wf.data?.instance ?? null}
                taxonomy={tax.data}
                opportunities={ops.data?.items ?? []}
                isOwner={isOwner}
                onChanged={() => {
                    reloadAll();
                    void reload();
                }}
            />
            <ErrorAlert error={wf.error ?? tax.error} />
            {h1Current ? (
                <Section title="Direction decision (H1)" description="Recorded. Changing the study type or the direction reopens H1 and everything after it.">
                    <p data-testid="h1-recorded" className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                        <StatusBadge status="valid" /> Signed by {h1Current.approver} · manifest {h1Current.content_manifest_hash.slice(0, 16)}
                    </p>
                </Section>
            ) : project.state === "DIRECTION_REVIEW" && isOwner && (ops.data?.items.length ?? 0) > 0 ? (
                <DirectionApproval
                    projectId={pid}
                    opportunities={ops.data?.items ?? []}
                    instance={wf.data?.instance ?? null}
                    declaration={approvals.data?.declarations.H1?.text}
                    onApproved={() => {
                        reloadAll();
                        void reload();
                    }}
                />
            ) : (
                <Section title="Direction decision (H1)" description="Recorded by the project owner while the project is in direction review.">
                    <p className="text-sm text-tertiary">
                        {project.state === "DIRECTION_REVIEW"
                            ? isOwner
                                ? "Generate or add proposals before recording H1."
                                : "Only the project owner can record H1."
                            : `H1 is recorded in direction review; the project is in ${project.state}.`}
                    </p>
                </Section>
            )}
        </div>
    );
}
