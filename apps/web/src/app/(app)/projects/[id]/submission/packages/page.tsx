"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TaskProgress } from "@/components/cfp/task-progress";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { PackageCard } from "@/components/submission/packages-list";
import { SubmissionNav } from "@/components/submission/submission-nav";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { PackagesView, Task } from "@/lib/api/types";

const ACTIVE = ["queued", "running", "failed_retryable"];

export default function PackagesPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const view = useResource<PackagesView>(pid ? `/v1/projects/${pid}/packages` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const pkgTasks = (tasks.data?.items ?? []).filter((t) => t.kind === "package_build");
    const active = pkgTasks.some((t) => ACTIVE.includes(t.state));
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
    const items = view.data?.items ?? [];
    return (
        <div className="flex flex-col gap-8">
            <SubmissionNav projectId={pid} />
            <Section
                title="Export packages"
                description={view.data ? <span data-testid="packages-notice">{view.data.notice}</span> : undefined}
            >
                <p className="text-sm text-secondary">
                    Before H4 a package can be built for author review; it is labelled UNAPPROVED. After H4 the package is built from the signed content manifest and its file hashes are verified by the server.
                </p>
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
                                        await api.post(`/v1/projects/${pid}/packages`, {});
                                        reloadAll();
                                    } catch (err) {
                                        setError(err);
                                    } finally {
                                        setBusy(false);
                                    }
                                }}
                            >
                                Build export package
                            </Button>
                        </div>
                        <ErrorAlert error={error} />
                    </div>
                )}
                {view.isLoading && !view.data && <Loading label="Loading packages" />}
                <ErrorAlert error={view.error} />
                {view.data && items.length === 0 && (
                    <p data-testid="packages-empty" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        No package has been built.
                    </p>
                )}
            </Section>
            <TaskProgress tasks={pkgTasks} title="Package tasks" onChanged={reloadAll} />
            {items.length > 0 && (
                <Section title="Packages">
                    <div className="flex flex-col gap-3">
                        {items.map((p) => (
                            <PackageCard key={p.id} p={p} />
                        ))}
                    </div>
                </Section>
            )}
        </div>
    );
}
