"use client";

import { useEffect } from "react";
import { ProtocolWorkspace } from "@/components/method/protocol-workspace";
import { StageList } from "@/components/method/stage-list";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { QUALITATIVE_STUDY_TYPES, isReviewStudyType } from "@/lib/synthesis";
import type { ApprovalsView, ProtocolList, Task, WorkflowDefinitionView } from "@/lib/api/types";

export default function MethodologyPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const wf = useResource<WorkflowDefinitionView>(pid ? `/v1/projects/${pid}/workflow-definition` : null);
    const protocols = useResource<ProtocolList>(pid ? `/v1/projects/${pid}/protocols` : null);
    const approvals = useResource<ApprovalsView>(pid ? `/v1/projects/${pid}/approvals` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const reviewing = (tasks.data?.items ?? []).some((t) => t.kind === "methodology_review" && ["queued", "running", "failed_retryable"].includes(t.state));
    const reloadAll = () => void Promise.all([wf.reload(), protocols.reload(), approvals.reload(), tasks.reload(), reload()]);

    useEffect(() => {
        reloadAll();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!reviewing) return;
        const id = setInterval(reloadAll, 2000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reviewing]);

    if (!project) return null;
    const isOwner = project.my_role === "owner";
    const canEdit = isOwner || project.my_role === "coauthor";
    const def = wf.data?.definition;
    const h1 = approvals.data?.items.find((a) => a.gate === "H1" && a.is_current);

    return (
        <div className="flex flex-col gap-10">
            <Section title="Method workflow" description="The selected method definition drives the protocol sections and the stages you complete after H2.">
                {wf.isLoading && !wf.data && <Loading label="Loading method" />}
                <ErrorAlert error={wf.error} />
                {wf.data && !wf.data.instance && (
                    <p className="text-sm text-tertiary">
                        No study type is selected. Choose one in{" "}
                        <a className="underline" href={`/projects/${pid}/direction`}>
                            research direction
                        </a>
                        .
                    </p>
                )}
                {def && wf.data?.instance && (
                    <div className="flex flex-col gap-1 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <p className="flex flex-wrap items-center gap-2 font-medium text-primary">
                            {def.title}
                            <StatusBadge status={def.enabled_for_submission_ready ? "method_enabled" : "method_planning_only"} />
                            <span className="text-xs font-normal text-tertiary">{wf.data.instance.definition_key}</span>
                        </p>
                        <p className="text-sm text-tertiary">{def.plain_definition}</p>
                        {def.reporting_standard && <p className="text-xs text-tertiary">Reporting standard: {def.reporting_standard}</p>}
                        {!h1 && <p className="text-sm text-warning-primary">Record H1 before drafting the protocol.</p>}
                    </div>
                )}
            </Section>
            {wf.data?.instance && (
                <>
                    <ErrorAlert error={protocols.error} />
                    <ProtocolWorkspace
                        projectId={pid}
                        list={protocols.data}
                        tasks={tasks.data?.items ?? []}
                        canEdit={canEdit}
                        isOwner={isOwner}
                        h2Declaration={approvals.data?.declarations.H2?.text}
                        onChanged={reloadAll}
                        studyType={wf.data.instance.study_type}
                    />
                    <Section
                        title="Method stages"
                        description={
                            wf.data.frozen_protocol_version
                                ? `Bound to frozen protocol v${wf.data.frozen_protocol_version}. Record each stage in the contribution workspace.`
                                : "Stages run only against the frozen (H2-approved) protocol."
                        }
                    >
                        <StageList stages={wf.data.stages} />
                        <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/contributions`}>
                            Open the contribution workspace
                        </a>
                        {isReviewStudyType(wf.data.instance.study_type) && (
                            <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/review-workspace`}>
                                Open the review workspace (searches, screening, extraction, synthesis)
                            </a>
                        )}
                        {QUALITATIVE_STUDY_TYPES.includes(wf.data.instance.study_type) && (
                            <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/qualitative`}>
                                Open the qualitative workspace (codebook, coded segments, themes)
                            </a>
                        )}
                        <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/experiments`}>
                            Plan and run sandboxed experiments under the frozen protocol
                        </a>
                    </Section>
                </>
            )}
        </div>
    );
}
