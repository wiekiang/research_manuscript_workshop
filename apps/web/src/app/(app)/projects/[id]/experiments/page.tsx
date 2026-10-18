"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/base/buttons/button";
import { PlanCard } from "@/components/experiments/plan-card";
import { PlanForm } from "@/components/experiments/plan-form";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import type { ContributionEntry, ExperimentsView, Task } from "@/lib/api/types";
import { ACTIVE_RUN_STATES } from "@/lib/experiments";

const EXPERIMENT_TASKS = ["experiment_run", "experiment_recompute"];

export default function ExperimentsPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const view = useResource<ExperimentsView>(pid ? `/v1/projects/${pid}/experiments` : null);
    const contributions = useResource<{ items: ContributionEntry[] }>(pid ? `/v1/projects/${pid}/contributions` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=50` : null);
    const [formOpen, setFormOpen] = useState(false);
    const plans = view.data?.items ?? [];
    const expTasks = (tasks.data?.items ?? []).filter((t) => EXPERIMENT_TASKS.includes(t.kind));
    const active = plans.some((p) => p.runs.some((r) => ACTIVE_RUN_STATES.includes(r.status)));
    const reloadAll = () => void Promise.all([view.reload(), tasks.reload(), contributions.reload(), reload()]);

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
    const isOwner = project.my_role === "owner";
    const files = (contributions.data?.items ?? []).filter((c) => c.artifact_id);

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Experiments"
                description={
                    <>
                        Sandboxed computational runs under the frozen (H2) protocol: pinned image, recorded code and input hashes, a fixed seed, resource limits and no network. A separate
                        validator recomputes the metrics from the stored raw outputs. Failed runs stay visible and never become results. Upload code and data on the{" "}
                        <Link href={`/projects/${pid}/contributions`} className="text-brand-secondary underline">
                            Contributions
                        </Link>{" "}
                        page and freeze the protocol under{" "}
                        <Link href={`/projects/${pid}/methodology`} className="text-brand-secondary underline">
                            Methodology & protocol
                        </Link>
                        .
                    </>
                }
                actions={
                    canEdit && (
                        <Button size="sm" onClick={() => setFormOpen(true)}>
                            New experiment plan
                        </Button>
                    )
                }
            >
                {view.isLoading && !view.data && <Loading label="Loading experiment plans" />}
                <ErrorAlert error={view.error} />
                {view.data && plans.length === 0 && (
                    <p data-testid="experiments-empty" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        No experiment plan yet. Plans can be drafted once the protocol is frozen at H2, and run only after the project owner approves them.
                    </p>
                )}
            </Section>

            {plans.length > 0 && (
                <Section title="Experiment plans" description="Each plan lists its runs, their independent recomputation and any reproduction rerun.">
                    <div className="flex flex-col gap-6">
                        {plans.map((p) => (
                            <PlanCard key={p.id} projectId={pid} plan={p} tasks={expTasks} isOwner={isOwner} canEdit={canEdit} onChanged={reloadAll} />
                        ))}
                    </div>
                </Section>
            )}

            {view.data && (
                <PlanForm projectId={pid} files={files} images={view.data.images} isOpen={formOpen} onOpenChange={setFormOpen} onCreated={reloadAll} />
            )}
        </div>
    );
}
