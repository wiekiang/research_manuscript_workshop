"use client";

import { useContext } from "react";
import { ProjectContext } from "@/components/project/project-context";
import { StatusBadge } from "@/components/research/status-badge";
import { TaskActions } from "@/components/research/task-actions";
import type { Task } from "@/lib/api/types";
import { relativeTime } from "@/lib/format";

const KIND_LABEL: Record<string, string> = {
    cfp_import: "Official URL import",
    cfp_extract_supplied: "Supplied document extraction",
    cfp_monitor: "CFP change check",
    conference_discovery: "Conference discovery",
    template_import: "Template retrieval and analysis",
    template_compile: "Sample compilation",
    literature_search: "Literature search / identity check",
    evidence_extraction: "Full-text retrieval and evidence extraction",
    claim_support_check: "Model-assisted support assessment",
    opportunity_generation: "Gap proposals",
    methodology_review: "Independent methodology review (model-assisted)",
    result_assessment: "Result assurance assessment (deterministic)",
    manuscript_generation: "Manuscript draft generation",
    manuscript_compile: "Manuscript compilation (sandbox)",
    review_run: "Independent review (scientific, citation/evidence, technical, compliance)",
    integrity_check: "Research integrity checks (deterministic)",
};

export function TaskProgress({ tasks, title = "CFP processing", onChanged }: { tasks: Task[]; title?: string; onChanged?: () => void }) {
    const ctx = useContext(ProjectContext);
    if (tasks.length === 0) return null;
    const project = ctx?.project;
    const canEdit = project?.my_role === "owner" || project?.my_role === "coauthor";
    const headingId = `tasks-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    return (
        <section aria-labelledby={headingId} className="flex flex-col gap-2">
            <h2 id={headingId} className="text-sm font-semibold text-secondary">
                {title}
            </h2>
            <ul className="flex flex-col gap-2" aria-live="polite">
                {tasks.slice(0, 4).map((t) => {
                    const passes = (t.result?.passes ?? null) as Record<string, string> | null;
                    return (
                        <li key={t.id} data-testid="cfp-task" data-state={t.state} className="flex flex-col gap-1 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm font-medium text-primary">{KIND_LABEL[t.kind] ?? t.kind}</span>
                                <StatusBadge status={t.state} />
                                <span className="text-xs text-tertiary">
                                    attempt {t.attempt}/{t.max_attempts} · {relativeTime(t.updated_at)}
                                </span>
                            </div>
                            {typeof t.params?.url === "string" && <p className="text-xs break-all text-tertiary">{t.params.url}</p>}
                            {t.error_message && (
                                <p className="text-sm text-error-primary">
                                    {t.error_code}: {t.error_message}
                                </p>
                            )}
                            {project && <TaskActions projectId={project.id} task={t} canEdit={canEdit} onChanged={onChanged ?? (() => void ctx?.reload())} />}
                            {passes && (
                                <p className="text-xs text-tertiary">
                                    Deterministic pass: {passes.deterministic}. Model extraction: {passes.model_extraction}. Independent validation: {passes.independent_validation}.
                                </p>
                            )}
                        </li>
                    );
                })}
            </ul>
        </section>
    );
}
