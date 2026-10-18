"use client";

import { Plus } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, PageHeader, Section } from "@/components/research/page-header";
import { StageTimeline } from "@/components/research/stage-timeline";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import type { Notification, Project } from "@/lib/api/types";
import { AVAILABILITY_LABEL, GLOBAL_WORKSPACES, PROJECT_WORKSPACES } from "@/lib/features";
import { relativeTime } from "@/lib/format";
import { HUMAN_GATE_STATES, transitionDescription } from "@/lib/states";
import { cx } from "@/utils/cx";

/** Live gate reasons from the API's next_step; falls back to the static transition text when absent. */
function NextStepSummary({ p }: { p: Project }) {
    const ns = p.next_step;
    const waiting = typeof p.waiting_human_tasks === "number" ? p.waiting_human_tasks : (p.waiting_human_tasks?.length ?? 0);
    const failing = (ns?.gates ?? []).filter((g) => !g.passed);
    return (
        <div className="flex flex-col gap-1 text-sm text-secondary" data-testid="card-next-step">
            <p>
                <span className="font-medium">Next: </span>
                {ns?.message ?? ns?.description ?? transitionDescription(p.state === "PAUSED" && p.resume_state ? p.resume_state : p.state) ?? "No further stage in this release."}
            </p>
            {ns?.ready && <p className="text-success-primary">All gates for the next stage are satisfied.</p>}
            {failing.length > 0 && (
                <ul className="list-disc pl-5 text-xs text-tertiary" aria-label="What is still needed">
                    {failing.flatMap((g) => (g.reasons.length ? g.reasons : [g.next_action ?? g.gate_id])).slice(0, 3).map((r) => (
                        <li key={r}>{r}</li>
                    ))}
                </ul>
            )}
            {waiting > 0 && <p className="text-xs text-utility-amber-700">{waiting} task{waiting === 1 ? "" : "s"} waiting for your decision</p>}
        </div>
    );
}

function ProjectCard({ p }: { p: Project }) {
    const gate = HUMAN_GATE_STATES[p.state];
    return (
        <li className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <h3 className="font-display text-lg font-semibold text-primary">
                        <a href={`/projects/${p.id}`} className="rounded outline-focus-ring hover:underline focus-visible:outline-2">
                            {p.title}
                        </a>
                    </h3>
                    {p.topic && <p className="truncate text-sm text-tertiary">{p.topic}</p>}
                </div>
                {gate ? <StatusBadge status="waiting_human" label={`Waiting for you: ${gate}`} /> : p.state === "CANCELLED" ? <StatusBadge status="cancelled" /> : p.state === "PAUSED" ? <StatusBadge status="paused" /> : null}
            </div>
            <StageTimeline state={p.state} resumeState={p.resume_state} compact />
            <NextStepSummary p={p} />
            <p className="text-xs text-tertiary">Updated {relativeTime(p.updated_at)} · your role: {p.my_role}</p>
        </li>
    );
}

export default function Dashboard() {
    const { data, error, isLoading } = useResource<{ items: Project[] }>("/v1/projects?limit=50");
    const { data: notes } = useResource<{ items: Notification[] }>("/v1/notifications?unread_only=true");

    return (
        <div className="flex flex-col gap-10">
            <PageHeader
                title="Your research projects"
                description="Each project shows its stage and the next decision that is yours to make."
                actions={
                    <Button iconLeading={Plus} href="/projects/new" size="md">
                        New project
                    </Button>
                }
            />
            <Section title="Projects">
                {isLoading && <Loading label="Loading projects" />}
                <ErrorAlert error={error} />
                {data && data.items.length === 0 && (
                    <div className="rounded-2xl border border-dashed border-primary p-8">
                        <p className="text-md font-semibold text-primary">No projects yet</p>
                        <p className="mt-1 text-sm text-tertiary">Start with the conference you are aiming for: create a project, then import its official call for papers.</p>
                        <div className="mt-4">
                            <Button href="/projects/new">Create your first project</Button>
                        </div>
                    </div>
                )}
                {data && data.items.length > 0 && (
                    <ul className="grid grid-cols-1 gap-4 md:grid-cols-2">
                        {data.items.map((p) => (
                            <ProjectCard key={p.id} p={p} />
                        ))}
                    </ul>
                )}
            </Section>
            {notes && notes.items.length > 0 && (
                <Section title="Needs your attention" description="Unread notifications about approvals, changed rules and budgets.">
                    <ul className="flex flex-col divide-y divide-secondary rounded-2xl bg-primary ring-1 ring-secondary">
                        {notes.items.slice(0, 6).map((n) => (
                            <li key={n.id} className="flex flex-col gap-0.5 p-4">
                                <a href={n.link ?? "/notifications"} className="text-sm font-semibold text-primary hover:underline">
                                    {n.title}
                                </a>
                                {n.body && <p className="text-sm text-tertiary">{n.body}</p>}
                                <p className="text-xs text-quaternary">{relativeTime(n.created_at)}</p>
                            </li>
                        ))}
                    </ul>
                </Section>
            )}
            <Section
                title="What runs in this release"
                description="Which stages the platform automates, which need your review, and which are not available yet. Unavailable stages never show sample data."
            >
                <div className="overflow-x-auto rounded-2xl bg-primary ring-1 ring-secondary">
                    <table className="w-full min-w-[640px] text-left text-sm">
                        <thead className="bg-secondary text-xs text-tertiary">
                            <tr>
                                <th scope="col" className="px-4 py-2 font-medium">
                                    Workspace
                                </th>
                                <th scope="col" className="px-4 py-2 font-medium">
                                    How it runs
                                </th>
                                <th scope="col" className="px-4 py-2 font-medium">
                                    Milestone
                                </th>
                                <th scope="col" className="px-4 py-2 font-medium">
                                    What it does
                                </th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-secondary">
                            {[...GLOBAL_WORKSPACES, ...PROJECT_WORKSPACES].map((w) => (
                                <tr key={w.key}>
                                    <th scope="row" className="px-4 py-2.5 font-medium text-primary">
                                        {w.label}
                                    </th>
                                    <td className={cx("px-4 py-2.5", w.availability === "unavailable" ? "text-quaternary" : "text-secondary")}>{AVAILABILITY_LABEL[w.availability]}</td>
                                    <td className="px-4 py-2.5 text-tertiary">{w.milestone}</td>
                                    <td className="px-4 py-2.5 text-tertiary">{w.summary}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </Section>
        </div>
    );
}
