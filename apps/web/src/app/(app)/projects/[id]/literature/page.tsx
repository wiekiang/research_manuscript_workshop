"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { TaskProgress } from "@/components/cfp/task-progress";
import { PapersPanel } from "@/components/literature/papers-panel";
import { LiteratureSetupPanel, SearchForm, SearchHistory } from "@/components/literature/search-panel";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import type { LiteratureSetup, PaperEntry, SearchRunEntry, Task } from "@/lib/api/types";

const LIT_TASKS = new Set(["literature_search", "evidence_extraction", "claim_support_check"]);

function LiteratureWorkspace() {
    const { project, taskTick } = useProject();
    const params = useSearchParams();
    const filter = params?.get("filter") ?? null;
    const pid = project?.id ?? "";
    const setup = useResource<LiteratureSetup>(pid ? "/v1/literature/setup" : null);
    const runs = useResource<{ items: SearchRunEntry[] }>(pid ? `/v1/projects/${pid}/searches` : null);
    const papers = useResource<{ items: PaperEntry[] }>(pid ? `/v1/projects/${pid}/papers` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const litTasks = (tasks.data?.items ?? []).filter((t) => LIT_TASKS.has(t.kind));
    const active = litTasks.some((t) => ["queued", "running", "failed_retryable"].includes(t.state));
    const reloadAll = () => void Promise.all([runs.reload(), papers.reload(), tasks.reload()]);

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
    return (
        <div className="flex flex-col gap-10">
            <LiteratureSetupPanel setup={setup} />
            {canEdit && <SearchForm projectId={pid} setup={setup.data} onQueued={reloadAll} />}
            <nav aria-label="Literature views" className="flex flex-wrap gap-4 text-sm">
                <a className="font-medium text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/literature/coverage`}>
                    Coverage report
                </a>
                <a className="font-medium text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/evidence`}>
                    Evidence and claims
                </a>
            </nav>
            <TaskProgress tasks={litTasks} title="Literature processing" />
            <ErrorAlert error={runs.error ?? papers.error} />
            {papers.isLoading && !papers.data ? <Loading label="Loading papers" /> : <PapersPanel projectId={pid} papers={papers.data?.items ?? []} canEdit={canEdit} onChanged={reloadAll} filter={filter} />}
            <SearchHistory runs={runs.data?.items ?? []} />
        </div>
    );
}

export default function Page() {
    return (
        <Suspense fallback={<Loading label="Loading literature" />}>
            <LiteratureWorkspace />
        </Suspense>
    );
}
