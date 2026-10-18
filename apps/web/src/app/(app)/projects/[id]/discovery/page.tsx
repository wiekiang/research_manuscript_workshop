"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Toggle } from "@/components/base/toggle/toggle";
import { TaskProgress } from "@/components/cfp/task-progress";
import { ProfileEditor } from "@/components/discovery/profile-editor";
import { ScoreBreakdown } from "@/components/discovery/score-breakdown";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { ApiError, api } from "@/lib/api/client";
import type { Candidate, Task } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";

const RUN_ERRORS: Record<string, { title: string; action: string }> = {
    profile_incomplete: { title: "Your research profile has no topics yet.", action: "Add at least one research topic in the profile above, save it, then run discovery again." },
    registry_empty: {
        title: "The curated official-source registry has no verified sources yet.",
        action: "Discovery only fetches organizer sources a platform operator has verified. Until then, import the official CFP URL directly in the Call for papers workspace.",
    },
};

function CandidateCard({ c, projectId, isOwner, onChanged }: { c: Candidate; projectId: string; isOwner: boolean; onChanged: () => void }) {
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<unknown>();
    const [imported, setImported] = useState(c.status === "imported");
    const act = async (kind: "import" | "dismiss") => {
        setBusy(kind);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/candidates/${c.id}/${kind}`);
            if (kind === "import") setImported(true);
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(null);
        }
    };
    return (
        <li data-testid="candidate" className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                    <p className="text-xs font-medium text-tertiary">Rank {c.rank}</p>
                    <h3 className="font-display text-lg font-semibold text-primary">
                        {c.name}
                        {c.acronym && <span className="text-tertiary"> · {c.acronym}</span>}
                        {c.year && <span className="text-tertiary"> {c.year}</span>}
                    </h3>
                    <a href={c.official_url} target="_blank" rel="noopener noreferrer" className="text-xs break-all text-brand-secondary hover:underline">
                        {c.official_url}
                    </a>
                </div>
                <div className="flex flex-wrap gap-2">
                    <StatusBadge status={c.status} />
                    {c.excluded && <StatusBadge status="blocked" label="Excluded" />}
                </div>
            </div>
            {c.exclusion_reason && <p className="text-sm text-secondary">Why it is set aside: {c.exclusion_reason}</p>}
            {c.tracks.length > 0 && <p className="text-sm text-secondary">Tracks found: {c.tracks.join(", ")}</p>}
            {c.deadlines.length > 0 && (
                <table className="w-full text-left text-sm">
                    <caption className="sr-only">Deadlines found in the official source (deterministic pass; import the CFP for verified rules)</caption>
                    <thead className="text-xs text-tertiary">
                        <tr>
                            <th className="py-1 pr-3 font-medium">Deadline</th>
                            <th className="py-1 pr-3 font-medium">Stated</th>
                            <th className="py-1 pr-3 font-medium">UTC</th>
                            <th className="py-1 font-medium">Problems</th>
                        </tr>
                    </thead>
                    <tbody>
                        {c.deadlines.map((d, i) => (
                            <tr key={`${d.kind}-${i}`} className="border-t border-secondary">
                                <td className="py-1 pr-3">{humanize(d.kind)}</td>
                                <td className="py-1 pr-3">
                                    {d.date ?? "—"} {d.timezone ?? <span className="text-tertiary">(no timezone stated)</span>}
                                </td>
                                <td className="py-1 pr-3">{d.due_at ? formatDateTime(d.due_at) : "unknown"}</td>
                                <td className="py-1 text-xs text-tertiary">{d.problems.join("; ") || "—"}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            <ScoreBreakdown components={c.components} total={c.total_score} />
            {c.questionable_evidence.length > 0 && (
                <div className="rounded-lg bg-warning-primary p-3 text-sm text-utility-amber-700">
                    <p className="font-semibold">Recorded concerns (cited evidence, not a platform judgement)</p>
                    <ul className="list-disc pl-5">
                        {c.questionable_evidence.map((e, i) => (
                            <li key={i}>
                                {e.note}{" "}
                                {e.source_url && (
                                    <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="underline">
                                        source
                                    </a>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <p className="text-xs text-tertiary">{c.note}</p>
            <ErrorAlert error={error} />
            {isOwner && (
                <div className="flex flex-wrap gap-2">
                    {imported ? (
                        <Button href={`/projects/${projectId}/cfp`} color="secondary">
                            Open CFP workspace
                        </Button>
                    ) : (
                        <Button onClick={() => void act("import")} isLoading={busy === "import"} isDisabled={c.status === "dismissed"}>
                            Import official CFP
                        </Button>
                    )}
                    {c.status !== "dismissed" && !imported && (
                        <Button color="tertiary" onClick={() => void act("dismiss")} isLoading={busy === "dismiss"}>
                            Dismiss
                        </Button>
                    )}
                </div>
            )}
        </li>
    );
}

export default function DiscoveryWorkspace() {
    const { project, taskTick } = useProject();
    const projectId = project?.id ?? "";
    const [includeExcluded, setIncludeExcluded] = useState(false);
    const candidates = useResource<{ items: Candidate[] }>(projectId ? `/v1/projects/${projectId}/candidates${includeExcluded ? "?include_excluded=true" : ""}` : null);
    const tasks = useResource<{ items: Task[] }>(projectId ? `/v1/projects/${projectId}/tasks?limit=20` : null);
    const [runError, setRunError] = useState<unknown>();
    const [running, setRunning] = useState(false);
    const discoveryTasks = (tasks.data?.items ?? []).filter((t) => t.kind === "conference_discovery" || (t.kind === "cfp_import" && !!t.params?.candidate_id));
    const active = discoveryTasks.some((t) => ["queued", "running", "failed_retryable"].includes(t.state));

    useEffect(() => {
        void tasks.reload();
        void candidates.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!active) {
            void candidates.reload();
            return;
        }
        const id = setInterval(() => void tasks.reload(), 1500);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    if (!project) return null;
    const isOwner = project.my_role === "owner";
    const code = runError instanceof ApiError ? runError.code : null;

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Your research profile for this project"
                description="Discovery ranks verified official organizer sources against this profile. Values you leave empty make the matching component unknown rather than zero."
            >
                <ProfileEditor projectId={project.id} />
            </Section>
            <Section
                title="Discover conferences"
                description="Fetches each verified official source through the controlled fetch service (respecting robots.txt), stores an immutable snapshot, and ranks it. Third-party listings are never used as the authoritative CFP."
                actions={
                    isOwner ? (
                        <Button
                            isLoading={running}
                            onClick={async () => {
                                setRunning(true);
                                setRunError(undefined);
                                try {
                                    await api.post(`/v1/projects/${project.id}/discovery`);
                                    void tasks.reload();
                                } catch (err) {
                                    setRunError(err);
                                } finally {
                                    setRunning(false);
                                }
                            }}
                        >
                            Run discovery
                        </Button>
                    ) : undefined
                }
            >
                {code && RUN_ERRORS[code] ? (
                    <div role="alert" data-testid="discovery-error" className="flex flex-col gap-1 rounded-xl bg-secondary_subtle p-4 text-sm ring-1 ring-secondary">
                        <p className="font-semibold text-primary">{RUN_ERRORS[code].title}</p>
                        <p className="text-secondary">{RUN_ERRORS[code].action}</p>
                        {code === "registry_empty" && (
                            <div className="mt-2 flex flex-wrap gap-2">
                                <Button href={`/projects/${project.id}/cfp`} color="secondary" size="sm">
                                    Import a CFP URL
                                </Button>
                                <Button href="/conferences/registry" color="link-color" size="sm">
                                    View the registry
                                </Button>
                            </div>
                        )}
                    </div>
                ) : (
                    <ErrorAlert error={runError} />
                )}
                <TaskProgress tasks={discoveryTasks} title="Discovery processing" />
            </Section>
            <Section title="Ranked candidates" actions={<Toggle isSelected={includeExcluded} onChange={setIncludeExcluded} label="Include excluded" />}>
                {candidates.isLoading && !candidates.data && <Loading label="Loading candidates" />}
                <ErrorAlert error={candidates.error} />
                {candidates.data && candidates.data.items.length === 0 && <p className="text-sm text-tertiary">No candidates yet. Run discovery after saving your profile.</p>}
                <ul className="flex flex-col gap-4">
                    {candidates.data?.items.map((c) => (
                        <CandidateCard key={c.id} c={c} projectId={project.id} isOwner={isOwner} onChanged={() => void Promise.all([candidates.reload(), tasks.reload()])} />
                    ))}
                </ul>
            </Section>
        </div>
    );
}
