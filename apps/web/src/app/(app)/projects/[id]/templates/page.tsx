"use client";

import { useEffect } from "react";
import { TaskProgress } from "@/components/cfp/task-progress";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { TemplateCard } from "@/components/templates/template-card";
import { TemplateImport } from "@/components/templates/template-import";
import { useResource } from "@/hooks/use-resource";
import type { Task, TemplateEntry } from "@/lib/api/types";

const TEMPLATE_TASKS = new Set(["template_import", "template_compile"]);

export default function TemplatesWorkspace() {
    const { project, taskTick } = useProject();
    const projectId = project?.id ?? "";
    const templates = useResource<{ items: TemplateEntry[] }>(projectId ? `/v1/projects/${projectId}/templates` : null);
    const tasks = useResource<{ items: Task[] }>(projectId ? `/v1/projects/${projectId}/tasks?limit=30` : null);
    const tplTasks = (tasks.data?.items ?? []).filter((t) => TEMPLATE_TASKS.has(t.kind));
    const active = tplTasks.some((t) => ["queued", "running", "failed_retryable"].includes(t.state)) || (templates.data?.items ?? []).some((t) => t.status === "analyzing");

    useEffect(() => {
        void templates.reload();
        void tasks.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!active) return;
        const id = setInterval(() => {
            void tasks.reload();
            void templates.reload();
        }, 2000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    if (!project) return null;
    const isOwner = project.my_role === "owner";
    const items = templates.data?.items ?? [];
    return (
        <div className="flex flex-col gap-10">
            {isOwner && (
                <TemplateImport
                    projectId={project.id}
                    onQueued={() => {
                        void tasks.reload();
                        void templates.reload();
                    }}
                />
            )}
            <TaskProgress tasks={tplTasks} title="Template processing" />
            <Section
                title="Template register"
                description="Each template records its official origin, checksum, license note and protected files. Sample compiles use fixed sample content, not your manuscript. A template without an adapter is labelled not submission-ready."
            >
                {templates.isLoading && !templates.data && <Loading label="Loading templates" />}
                <ErrorAlert error={templates.error} />
                {templates.data && items.length === 0 && <p className="text-sm text-tertiary">No template added yet.</p>}
                <div className="flex flex-col gap-6">
                    {items.map((t) => (
                        <TemplateCard key={t.id} projectId={project.id} t={t} isOwner={isOwner} onChanged={() => void Promise.all([templates.reload(), tasks.reload()])} />
                    ))}
                </div>
            </Section>
        </div>
    );
}
