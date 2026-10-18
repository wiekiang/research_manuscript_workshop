"use client";

import { useEffect } from "react";
import type { ReactNode } from "react";
import { useParams, usePathname } from "next/navigation";
import { ProviderBadge } from "@/components/model-provider/provider-badge";
import { ProjectProvider, useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading } from "@/components/research/page-header";
import { StageTimeline } from "@/components/research/stage-timeline";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import type { WorkflowDefinitionView } from "@/lib/api/types";
import { workspacesFor } from "@/lib/features";
import { HUMAN_GATE_STATES } from "@/lib/states";
import { cx } from "@/utils/cx";

function ProjectChrome({ projectId, children }: { projectId: string; children: ReactNode }) {
    const { project, error, isLoading, live, eventTick } = useProject();
    const wf = useResource<WorkflowDefinitionView>(project?.method_instance_id ? `/v1/projects/${projectId}/workflow-definition` : null);
    const studyType = wf.data?.instance?.study_type ?? null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => void wf.reload(), [eventTick, project?.method_instance_id]);
    const pathname = usePathname() ?? "";
    const segment = pathname.split("/")[3] ?? "";

    if (isLoading && !project) return <Loading label="Loading project" />;
    if (error && !project) return <ErrorAlert error={error} title="This project could not be opened" />;
    if (!project) return null;
    const waiting = HUMAN_GATE_STATES[project.state];

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-col gap-1">
                        <a href="/dashboard" className="text-sm text-tertiary underline-offset-2 hover:underline">
                            All projects
                        </a>
                        <h1 className="font-display text-display-xs font-semibold text-primary">{project.title}</h1>
                        {project.topic && <p className="text-sm text-tertiary">{project.topic}</p>}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        {waiting && <StatusBadge status="waiting_human" label={`Waiting for you: ${waiting}`} />}
                        {project.state === "PAUSED" && <StatusBadge status="paused" />}
                        {project.state === "CANCELLED" && <StatusBadge status="cancelled" />}
                        <ProviderBadge projectId={projectId} tick={eventTick} />
                        <span className="text-xs text-tertiary" aria-live="polite">
                            {live === "live" ? "Live updates on" : live === "connecting" ? "Connecting to live updates" : "Live updates paused; reload to refresh"}
                        </span>
                    </div>
                </div>
                <StageTimeline state={project.state} resumeState={project.resume_state} compact />
            </div>
            <nav aria-label="Project workspaces" className="-mx-1 overflow-x-auto">
                <ul className="flex min-w-max gap-1 border-b border-secondary px-1">
                    {workspacesFor(studyType).map((w) => {
                        const active = segment === w.segment;
                        return (
                            <li key={w.key}>
                                <a
                                    href={`/projects/${projectId}${w.segment ? `/${w.segment}` : ""}`}
                                    aria-current={active ? "page" : undefined}
                                    className={cx(
                                        "flex items-center gap-1.5 rounded-t-md border-b-2 px-3 py-2 text-sm font-medium outline-focus-ring focus-visible:outline-2",
                                        active ? "border-brand text-brand-secondary" : "border-transparent text-tertiary hover:text-secondary",
                                        w.availability === "unavailable" && "text-quaternary",
                                    )}
                                >
                                    <w.icon className="size-4" aria-hidden="true" />
                                    {w.label}
                                    {w.availability === "unavailable" && <span className="sr-only"> (not available in this release)</span>}
                                </a>
                            </li>
                        );
                    })}
                </ul>
            </nav>
            <div>{children}</div>
        </div>
    );
}

export default function ProjectLayout({ children }: { children: ReactNode }) {
    const params = useParams<{ id: string }>();
    return (
        <ProjectProvider projectId={params.id}>
            <ProjectChrome projectId={params.id}>{children}</ProjectChrome>
        </ProjectProvider>
    );
}
