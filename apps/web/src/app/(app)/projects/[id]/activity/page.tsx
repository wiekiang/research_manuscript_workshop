"use client";

import { useEffect } from "react";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { TaskActions } from "@/components/research/task-actions";
import { useResource } from "@/hooks/use-resource";
import type { ProjectEvent, ProjectState, Task } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import { STATE_LABEL } from "@/lib/states";

function stateName(s: string | null): string {
    return s ? (STATE_LABEL[s as ProjectState] ?? s) : "—";
}

export default function ActivityPage() {
    const { project, eventTick, taskTick } = useProject();
    const id = project?.id;
    const tasks = useResource<{ items: Task[] }>(id ? `/v1/projects/${id}/tasks?limit=100` : null);
    const events = useResource<{ items: ProjectEvent[] }>(id ? `/v1/projects/${id}/events?limit=500` : null);
    useEffect(() => {
        void tasks.reload();
        void events.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [eventTick, taskTick]);
    if (!project) return null;

    return (
        <div className="flex flex-col gap-10">
            <Section title="Agent and workflow tasks" description="Every automated task, who owns it, its retries and its committed outputs. Failed tasks never produce findings.">
                {tasks.isLoading && <Loading label="Loading tasks" />}
                <ErrorAlert error={tasks.error} />
                {tasks.data && tasks.data.items.length === 0 && <p className="text-sm text-tertiary">No tasks have run yet.</p>}
                <ul className="flex flex-col gap-2">
                    {tasks.data?.items.map((t) => (
                        <li key={t.id} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm font-semibold text-primary">{humanize(t.kind)}</span>
                                <StatusBadge status={t.state} />
                                <span className="text-xs text-tertiary">
                                    Owner: {t.owner} · attempt {t.attempt} of {t.max_attempts}
                                </span>
                            </div>
                            <p className="text-xs text-tertiary">
                                Queued {formatDateTime(t.created_at)}
                                {t.started_at && ` · started ${formatDateTime(t.started_at)}`}
                                {t.finished_at && ` · finished ${formatDateTime(t.finished_at)}`}
                            </p>
                            {t.waiting_reason && <p className="text-sm text-utility-amber-700">Waiting: {t.waiting_reason}</p>}
                            {t.error_message && (
                                <p className="text-sm text-error-primary">
                                    {t.error_code}: {t.error_message}
                                </p>
                            )}
                            <TaskActions projectId={id ?? ""} task={t} canEdit={project?.my_role === "owner" || project?.my_role === "coauthor"} onChanged={() => void tasks.reload()} />
                            {t.output_artifact_ids.length > 0 && (
                                <div className="flex flex-wrap gap-3">
                                    {t.output_artifact_ids.map((a) => (
                                        <ArtifactLink key={a} artifactId={a} label="Output" />
                                    ))}
                                </div>
                            )}
                        </li>
                    ))}
                </ul>
            </Section>
            <Section title="Event and audit history" description="Append-only. Each state change shows who requested it and which gates were evaluated.">
                {events.isLoading && <Loading label="Loading history" />}
                <ErrorAlert error={events.error} />
                <ol className="flex flex-col gap-0 border-l-2 border-secondary pl-5" data-testid="event-timeline">
                    {events.data?.items
                        .slice()
                        .reverse()
                        .map((e) => (
                            <li key={e.id} className="relative pb-5" data-testid={`event-${e.type}`}>
                                <span aria-hidden="true" className="absolute top-1.5 -left-[27px] size-3 rounded-full bg-brand-solid ring-4 ring-primary" />
                                <p className="text-sm font-semibold text-primary">
                                    {e.type === "state.changed" ? `${stateName(e.from_state)} → ${stateName(e.to_state)}` : humanize(e.type)}
                                </p>
                                <p className="text-xs text-tertiary">
                                    #{e.seq} · {formatDateTime(e.occurred_at)} · {e.actor_type} {e.actor_type === "service" ? e.actor_id : ""}
                                    {typeof e.payload?.cause === "string" && ` · cause: ${e.payload.cause}`}
                                </p>
                                {typeof e.payload?.reason === "string" && e.payload.reason && <p className="text-sm text-secondary">Reason: {e.payload.reason}</p>}
                                {(e.gate_results?.results ?? []).length > 0 && (
                                    <ul className="mt-1 text-xs text-tertiary">
                                        {(e.gate_results.results ?? []).map((g) => (
                                            <li key={g.gate_id}>
                                                {g.passed ? "Passed" : "Failed"}: {g.gate_id}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </li>
                        ))}
                </ol>
            </Section>
        </div>
    );
}
