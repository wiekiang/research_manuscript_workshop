"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { DeadlinesTable } from "@/components/cfp/deadlines-table";
import { ImportPanel } from "@/components/cfp/import-panel";
import { ResolveDialog } from "@/components/cfp/resolve-dialog";
import { RulesList } from "@/components/cfp/rules-list";
import { TargetDialog } from "@/components/cfp/target-dialog";
import { TaskProgress } from "@/components/cfp/task-progress";
import { useProject } from "@/components/project/project-context";
import { ApprovalPanel } from "@/components/research/approval-panel";
import { ErrorAlert } from "@/components/research/error-alert";
import { Field, Loading, Section } from "@/components/research/page-header";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { FixtureNotice } from "@/components/research/verification-method-label";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { CfpRule, EditionView, ProjectCfp, Task } from "@/lib/api/types";
import { MonitorPanel } from "@/components/cfp/monitor-panel";
import { ruleModelProvider } from "@/components/cfp/rules-list";
import { formatDateTime, humanize } from "@/lib/format";
import { STATE_LABEL } from "@/lib/states";

const CFP_TASKS = new Set(["cfp_import", "cfp_extract_supplied", "cfp_monitor"]);

function Snapshots({ edition }: { edition: EditionView }) {
    return (
        <ul className="flex flex-col gap-2">
            {edition.snapshots.map((s) => (
                <li key={s.id} className="flex flex-col gap-1 rounded-xl bg-secondary_subtle p-3 text-sm ring-1 ring-secondary">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-primary">{s.origin === "fetched" ? "Fetched by the controlled fetch service" : "Supplied by a researcher"}</span>
                        <span className="text-xs text-tertiary">{formatDateTime(s.retrieved_at)}</span>
                        <span className="text-xs text-tertiary">· {humanize(s.verification_status)}</span>
                    </div>
                    <p className="text-xs break-all text-secondary">{s.final_url ?? s.url}</p>
                    {s.declared_origin && <p className="text-xs text-tertiary">Declared origin: {s.declared_origin}</p>}
                    {s.hops.length > 0 && <p className="text-xs text-tertiary">Route: {s.hops.map((h) => `${h.status} via ${h.ip}`).join(" → ")}</p>}
                    {(s.scan_report.flags ?? []).length > 0 && <p className="text-xs text-tertiary">Quarantine scan: {(s.scan_report.flags ?? []).join("; ")}</p>}
                    <ArtifactLink artifactId={s.artifact_id} hash={s.content_hash} label="Source snapshot" />
                </li>
            ))}
        </ul>
    );
}

export default function CfpWorkspace() {
    const { project, reload: reloadProject, eventTick, taskTick } = useProject();
    const projectId = project?.id ?? "";
    const cfp = useResource<ProjectCfp>(projectId ? `/v1/projects/${projectId}/cfp` : null);
    const tasks = useResource<{ items: Task[] }>(projectId ? `/v1/projects/${projectId}/tasks?limit=20` : null);
    const [resolving, setResolving] = useState<CfpRule | null>(null);
    const [targetOpen, setTargetOpen] = useState(false);
    const [confirmed, setConfirmed] = useState<string | null>(null);

    const cfpTasks = (tasks.data?.items ?? []).filter((t) => CFP_TASKS.has(t.kind));
    const active = cfpTasks.some((t) => ["queued", "running", "failed_retryable"].includes(t.state));

    useEffect(() => {
        void cfp.reload();
        void tasks.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [eventTick, taskTick]);
    useEffect(() => {
        if (!active) {
            void cfp.reload();
            return;
        }
        const id = setInterval(() => {
            void tasks.reload();
            void cfp.reload();
        }, 1500);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    if (!project) return null;
    const isOwner = project.my_role === "owner";
    const data = cfp.data;
    const target = data?.editions.find((e) => e.is_target);
    const modelProvider = data?.editions.flatMap((e) => e.rules).map(ruleModelProvider).find((p) => p) ?? null;
    const changedRules = (target?.rules ?? []).filter((r) => r.change_kind === "changed" || r.change_kind === "removed");
    const refreshAll = async () => {
        await Promise.all([cfp.reload(), reloadProject(), tasks.reload()]);
    };

    return (
        <div className="flex flex-col gap-10">
            <ImportPanel projectId={project.id} onQueued={() => void tasks.reload()} />
            <TaskProgress tasks={cfpTasks} />
            {cfp.isLoading && !data && <Loading label="Loading CFP register" />}
            <ErrorAlert error={cfp.error} />
            {data && data.editions.length === 0 && !active && <p className="text-sm text-tertiary">No CFP imported for this project yet.</p>}
            <FixtureNotice provider={modelProvider} />
            {changedRules.length > 0 && (
                <div role="alert" data-testid="changed-rules-banner" className="rounded-xl bg-warning-primary p-4 text-sm text-utility-amber-700 ring-1 ring-utility-amber-200">
                    <p className="font-semibold">The official CFP changed.</p>
                    <p>
                        {changedRules.length} rule{changedRules.length === 1 ? "" : "s"} changed or disappeared from the latest snapshot ({changedRules.map((r) => r.rule_key).join(", ")}). Review
                        them below; confirmations that depended on them have been reopened.
                    </p>
                </div>
            )}
            {data && target && <MonitorPanel projectId={project.id} isOwner={isOwner} onQueued={() => void tasks.reload()} />}

            {data?.editions.map((ed) => {
                const trackName = ed.is_target ? ed.tracks.find((t) => t.id === data.target.track_id)?.name : null;
                return (
                    <article key={ed.edition.id} aria-labelledby={`ed-${ed.edition.id}`} className="flex flex-col gap-8">
                        <header className="flex flex-col gap-3 border-b border-secondary pb-4">
                            <div className="flex flex-wrap items-center gap-3">
                                <h2 id={`ed-${ed.edition.id}`} className="font-display text-display-xs font-semibold text-primary">
                                    {ed.edition.name}
                                </h2>
                                {ed.is_target ? <StatusBadge status="confirmed" label={`Target (${data.target.mode})${trackName ? `: ${trackName}` : ""}`} /> : <StatusBadge status="queued" label="Not your target" />}
                                {ed.open_items > 0 && <StatusBadge status="needs_human_resolution" label={`${ed.open_items} item${ed.open_items === 1 ? "" : "s"} need your resolution`} />}
                            </div>
                            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                                <Field label="Year">{ed.edition.year ?? "—"}</Field>
                                <Field label="Location">{ed.edition.location ?? "—"}</Field>
                                <Field label="Publication">{ed.edition.publication_outlet ?? "—"}</Field>
                                <Field label="Venue status">{humanize(ed.edition.status)}</Field>
                            </dl>
                            {isOwner && (
                                <div>
                                    <Button color={ed.is_target ? "secondary" : "primary"} onClick={() => setTargetOpen(true)}>
                                        {ed.is_target ? "Change target track" : "Select target track"}
                                    </Button>
                                </div>
                            )}
                        </header>
                        <Section title="Tracks">
                            <ul className="flex flex-wrap gap-2">
                                {ed.tracks.map((t) => (
                                    <li key={t.id} className="rounded-lg bg-primary px-3 py-1.5 text-sm text-secondary ring-1 ring-secondary">
                                        {t.name}
                                        {t.id === data.target.track_id && <span className="text-brand-secondary"> · selected</span>}
                                    </li>
                                ))}
                            </ul>
                        </Section>
                        <Section title="Source snapshots" description="Immutable copies the rules below are quoted from. Rules cite the section and character offsets of their source sentence.">
                            <Snapshots edition={ed} />
                        </Section>
                        <Section title="Deadlines" description="Each deadline keeps the timezone the official source states. Missing or ambiguous timezones are never guessed.">
                            <DeadlinesTable deadlines={ed.deadlines} rules={ed.rules} canResolve={isOwner} onResolve={setResolving} />
                        </Section>
                        <Section
                            title="Submission rules"
                            description="Extracted by a deterministic pass and, where a model is configured, a model pass checked by an independent validator. Precedence when sources conflict: track CFP, then conference instructions, publisher policy, template documentation; conflicts are never resolved silently."
                        >
                            <RulesList rules={ed.rules} canResolve={isOwner} onResolve={setResolving} />
                        </Section>
                    </article>
                );
            })}

            {data && target && (
                <ApprovalPanel
                    gate="CFP"
                    title="Confirm the track and its blocking rules"
                    declaration={data.declaration.text}
                    blockingReasons={data.gate.passed ? [] : data.gate.reasons.filter((r) => !r.startsWith("confirm the selected track"))}
                    submitLabel="Confirm CFP rules"
                    onSubmit={async (body) => {
                        const res = await api.post<{ state: string; approval_id: string }>(`/v1/projects/${project.id}/cfp/confirm`, body);
                        setConfirmed(res.state);
                        await refreshAll();
                    }}
                />
            )}
            {confirmed && (
                <p role="status" className="rounded-xl bg-success-primary p-4 text-sm text-success-primary">
                    CFP rules confirmed. The project is now in {STATE_LABEL[confirmed as keyof typeof STATE_LABEL] ?? confirmed}.
                </p>
            )}

            <ResolveDialog projectId={project.id} rule={resolving} onClose={() => setResolving(null)} onResolved={() => void refreshAll()} />
            {data && (
                <TargetDialog
                    isOpen={targetOpen}
                    onClose={() => setTargetOpen(false)}
                    projectId={project.id}
                    projectVersion={project.version}
                    editions={data.editions}
                    onSelected={() => void refreshAll()}
                />
            )}
        </div>
    );
}
