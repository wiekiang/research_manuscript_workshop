"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { useProject } from "@/components/project/project-context";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { ContributionsPanel } from "@/components/method/contributions-panel";
import { ResultsPanel } from "@/components/method/results-panel";
import { StageForms } from "@/components/method/stage-forms";
import { TaskProgress } from "@/components/cfp/task-progress";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { ContributionEntry, LedgerEntry, ProtocolList, ResultEntry, Task, WorkflowDefinitionView } from "@/lib/api/types";
import { COPY } from "@/lib/copy";
import { formatDateTime, humanize } from "@/lib/format";
import { useSession } from "@/providers/session";

const CATEGORIES = ["idea", "question_refinement", "methodology_edit", "supplied_data", "analysis", "interpretation", "manuscript_change", "theoretical_work", "other"];

type Mode = { kind: "add" } | { kind: "correct"; entry: LedgerEntry } | { kind: "context"; entry: LedgerEntry } | null;

export default function ContributionsPage() {
    const { project, taskTick, reload } = useProject();
    const { me } = useSession();
    const pid = project?.id ?? "";
    const ledger = useResource<{ items: LedgerEntry[]; note: string }>(project ? `/v1/projects/${project.id}/contribution-ledger` : null);
    const contribs = useResource<{ items: ContributionEntry[]; title: string; fields: string[] }>(pid ? `/v1/projects/${pid}/contributions` : null);
    const results = useResource<{ items: ResultEntry[]; attestation_text: string }>(pid ? `/v1/projects/${pid}/results` : null);
    const protocols = useResource<ProtocolList>(pid ? `/v1/projects/${pid}/protocols` : null);
    const wf = useResource<WorkflowDefinitionView>(pid ? `/v1/projects/${pid}/workflow-definition` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const assessing = (tasks.data?.items ?? []).some((t) => t.kind === "result_assessment" && ["queued", "running", "failed_retryable"].includes(t.state));
    const reloadWork = () => void Promise.all([contribs.reload(), results.reload(), protocols.reload(), wf.reload(), tasks.reload(), ledger.reload(), reload()]);
    useEffect(() => {
        reloadWork();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!assessing) return;
        const id = setInterval(reloadWork, 2000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [assessing]);
    const [mode, setMode] = useState<Mode>(null);
    const [category, setCategory] = useState("idea");
    const [summary, setSummary] = useState("");
    const [rationale, setRationale] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [diffOpen, setDiffOpen] = useState<string | null>(null);
    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";

    const open = (m: Mode) => {
        setMode(m);
        setError(undefined);
        if (m && m.kind !== "add") {
            setCategory(m.entry.category);
            setSummary(m.kind === "correct" ? m.entry.summary : "");
            setRationale(m.entry.rationale ?? "");
        } else {
            setCategory("idea");
            setSummary("");
            setRationale("");
        }
    };

    const save = async () => {
        if (!mode) return;
        setBusy(true);
        setError(undefined);
        try {
            const base = `/v1/projects/${project.id}/contribution-ledger`;
            if (mode.kind === "add") await api.post(base, { category, summary, rationale: rationale || null });
            if (mode.kind === "correct") await api.post(`${base}/${mode.entry.id}/correct`, { category, summary, rationale: rationale || null });
            if (mode.kind === "context") await api.post(`${base}/${mode.entry.id}/context`, { rationale });
            setMode(null);
            await ledger.reload();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-10">
            <Section
                title={COPY.contribution_workspace_title}
                description="Record the substantive scientific work you do: data, code, results, stages and interpretation. Outcome review and H3 are on the outcomes page."
            >
                <ul className="flex flex-wrap gap-2" aria-label="Workspace areas">
                    {COPY.contribution_workspace_fields.map((f) => (
                        <li key={f} className="rounded-lg bg-secondary px-2.5 py-1 text-xs font-medium text-secondary">
                            {f}
                        </li>
                    ))}
                </ul>
                <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/contributions/outcomes`}>
                    Contribution matrix, gap assessment and H3
                </a>
                <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/experiments`}>
                    Sandboxed experiment runs (platform-executed results)
                </a>
            </Section>
            <ErrorAlert error={contribs.error ?? results.error ?? wf.error} />
            <ContributionsPanel projectId={pid} items={contribs.data?.items ?? []} canEdit={canEdit} onChanged={reloadWork} />
            <TaskProgress tasks={(tasks.data?.items ?? []).filter((t) => t.kind === "result_assessment")} title="Result assurance assessment" />
            <ResultsPanel
                projectId={pid}
                results={results.data?.items ?? []}
                attestation={results.data?.attestation_text}
                frozen={protocols.data?.items.find((p) => p.status === "frozen")}
                contributions={contribs.data?.items ?? []}
                canEdit={canEdit}
                onChanged={reloadWork}
            />
            <StageForms projectId={pid} stages={wf.data?.stages ?? []} contributions={contribs.data?.items ?? []} results={results.data?.items ?? []} canEdit={canEdit} onChanged={reloadWork} />
            <Section
                title="Contribution ledger"
                description={ledger.data?.note ?? "Evidence for author review, not an authorship certification."}
                actions={
                    canEdit && (
                        <>
                            <Button color="secondary" onClick={() => open({ kind: "add" })}>
                                Add a contribution
                            </Button>
                            <Button
                                color="secondary"
                                onClick={async () => {
                                    await api.post(`/v1/projects/${project.id}/contribution-ledger/verify`);
                                    await ledger.reload();
                                }}
                            >
                                Verify my record
                            </Button>
                        </>
                    )
                }
            >
                {ledger.isLoading && <Loading label="Loading ledger" />}
                <ErrorAlert error={ledger.error} />
                {ledger.data && ledger.data.items.length === 0 && (
                    <p className="text-sm text-tertiary">No contributions recorded yet. Substantive actions are captured automatically as you work; you can also add entries yourself.</p>
                )}
                <ul className="flex flex-col gap-2">
                    {ledger.data?.items.map((e) => {
                        const mine = e.user_id === me?.user.id;
                        return (
                            <li key={e.id} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-sm font-semibold text-primary">{humanize(e.category)}</span>
                                    <span className="text-xs text-tertiary">{e.contributor}</span>
                                    <span className="text-xs text-tertiary">{e.auto_captured ? "Captured automatically" : "Added by the contributor"}</span>
                                    <StatusBadge status={e.status === "verified" ? "confirmed" : e.status === "corrected" ? "superseded" : "queued"} label={humanize(e.status)} />
                                </div>
                                <p className="text-sm text-primary">{e.summary}</p>
                                {e.rationale && <p className="text-sm text-secondary">Context: {e.rationale}</p>}
                                {e.rationale_requested && mine && <p className="text-sm text-utility-amber-700">Please add context explaining this contribution.</p>}
                                <p className="text-xs text-tertiary">
                                    {formatDateTime(e.created_at)} · source: {humanize(e.source_action)}
                                </p>
                                {e.diff && (
                                    <div>
                                        <Button size="sm" color="link-color" onClick={() => setDiffOpen(diffOpen === e.id ? null : e.id)} aria-expanded={diffOpen === e.id}>
                                            {diffOpen === e.id ? "Hide change" : "Show change"}
                                        </Button>
                                        {diffOpen === e.id && <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-secondary p-3 text-xs text-secondary">{e.diff}</pre>}
                                    </div>
                                )}
                                {mine && canEdit && e.status !== "corrected" && (
                                    <div className="flex gap-2">
                                        <Button size="sm" color="secondary" onClick={() => open({ kind: "correct", entry: e })}>
                                            Correct
                                        </Button>
                                        <Button size="sm" color="secondary" onClick={() => open({ kind: "context", entry: e })}>
                                            Add context
                                        </Button>
                                    </div>
                                )}
                            </li>
                        );
                    })}
                </ul>
            </Section>
            <DialogShell
                isOpen={mode !== null}
                onOpenChange={(o) => !o && setMode(null)}
                title={mode?.kind === "add" ? "Add a contribution" : mode?.kind === "correct" ? "Correct this entry" : "Add context"}
                description={mode?.kind === "correct" ? "The original entry is kept and marked corrected." : undefined}
                footer={
                    <>
                        <Button color="secondary" onClick={() => setMode(null)}>
                            Cancel
                        </Button>
                        <Button isLoading={busy} onClick={save} isDisabled={mode?.kind === "context" ? rationale.trim().length < 3 : summary.trim().length < 3}>
                            Save
                        </Button>
                    </>
                }
            >
                {mode?.kind !== "context" && (
                    <>
                        <NativeSelect label="Category" value={category} onChange={(e) => setCategory(e.target.value)} options={CATEGORIES.map((c) => ({ label: humanize(c), value: c }))} />
                        <TextArea label="What you contributed" value={summary} onChange={setSummary} rows={3} />
                    </>
                )}
                <TextArea label={mode?.kind === "context" ? "Context" : "Rationale (optional)"} value={rationale} onChange={setRationale} rows={3} />
                <ErrorAlert error={error} />
            </DialogShell>
        </div>
    );
}
