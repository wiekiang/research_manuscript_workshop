"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TaskProgress } from "@/components/cfp/task-progress";
import { CandidatesPanel } from "@/components/manuscript/candidates-panel";
import { CompilePanel } from "@/components/manuscript/compile-panel";
import { DraftRequest } from "@/components/manuscript/draft-request";
import { SectionEditor } from "@/components/manuscript/section-editor";
import { SpanView, TableView } from "@/components/manuscript/span-view";
import { VersionsPanel } from "@/components/manuscript/versions-panel";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { ManuscriptView, Task, TemplateEntry } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { GAP_SECTION_LABEL, VERSION_ORIGIN_LABEL, spansBySection, tableAnchor, tableIssuesFor } from "@/lib/manuscript";

const ACTIVE = ["queued", "running", "failed_retryable"];

export default function ManuscriptPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const ms = useResource<ManuscriptView>(pid ? `/v1/projects/${pid}/manuscript` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const templates = useResource<{ items: TemplateEntry[] }>(pid ? `/v1/projects/${pid}/templates` : null);
    const [editing, setEditing] = useState<string | null>(null);
    const [tick, setTick] = useState(0);
    const [advanceError, setAdvanceError] = useState<unknown>();
    const [advancing, setAdvancing] = useState(false);
    const msTasks = (tasks.data?.items ?? []).filter((t) => t.kind === "manuscript_generation" || t.kind === "manuscript_compile");
    const active = msTasks.some((t) => ACTIVE.includes(t.state));
    const reloadAll = () => {
        setTick((t) => t + 1);
        void Promise.all([ms.reload(), tasks.reload(), templates.reload(), reload()]);
    };

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
    const isOwner = project.my_role === "owner";
    const canEdit = isOwner || project.my_role === "coauthor";
    const m = ms.data?.manuscript;
    const v = m?.current_version;
    const content = v?.content;
    const records = spansBySection(v?.spans ?? []);
    const gate = project.next_step?.gates.find((g) => g.gate_id === "manuscript.complete");

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Manuscript"
                description="Every sentence declares its kind and cites the verified claims or committed results it relies on. Deterministic checks run on each committed version."
            >
                {ms.isLoading && !ms.data && <Loading label="Loading manuscript" />}
                <ErrorAlert error={ms.error} />
                {ms.data && !m && (
                    <p data-testid="manuscript-empty" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        No manuscript yet. Request a draft once research is active; before H3 only a private research proposal can be drafted, and after H3 the manuscript is drafted as a paper.
                    </p>
                )}
                {m && v && (
                    <div data-testid="manuscript-summary" className="flex flex-wrap items-center gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <span className="font-medium text-primary">{content?.title ?? m.title}</span>
                        {content && <StatusBadge status={content.mode === "proposal" ? "proposal_mode" : "paper_mode"} />}
                        <span className="text-sm text-secondary" data-testid="current-version">
                            Version {v.version}
                        </span>
                        <span className="text-xs text-tertiary">
                            {VERSION_ORIGIN_LABEL[v.origin] ?? v.origin} · {formatDateTime(v.created_at)}
                        </span>
                        <span className="text-xs text-tertiary">
                            {v.checks.spans ?? 0} sentences · {v.checks.blockers ?? 0} blocker(s) · {v.checks.unresolved_claims ?? 0} unresolved claim(s) · {(v.checks.table_issues ?? []).length} table issue(s) ·
                            abstract {v.checks.abstract_words ?? 0} words
                        </span>
                    </div>
                )}
            </Section>

            <TaskProgress tasks={msTasks} title="Drafting and compilation" />
            <DraftRequest
                projectId={pid}
                sections={(content?.sections ?? []).map((s) => ({ key: s.key, heading: s.heading }))}
                canEdit={canEdit}
                onRequested={reloadAll}
            />

            {m && v && (
                <>
                    <CandidatesPanel manuscriptId={m.id} candidates={ms.data?.candidates ?? []} currentVersionId={v.id} currentVersion={v.version} canEdit={canEdit} onChanged={reloadAll} />

                    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
                        <div className="flex flex-col gap-8">
                            {(content?.sections ?? []).map((s) => (
                                <section key={s.key} aria-labelledby={`ms-${s.key}`} data-testid="manuscript-section" data-section={s.key} className="flex flex-col gap-3">
                                    <div className="flex items-center gap-3">
                                        <h2 id={`ms-${s.key}`} className="font-display text-lg font-semibold text-primary">
                                            {s.heading}
                                        </h2>
                                        {canEdit && editing !== s.key && (
                                            <Button size="sm" color="link-color" onClick={() => setEditing(s.key)}>
                                                Edit section
                                            </Button>
                                        )}
                                    </div>
                                    {editing === s.key ? (
                                        <SectionEditor
                                            manuscriptId={m.id}
                                            section={s}
                                            expectedVersion={v.version}
                                            tableIssues={(v.checks.table_issues ?? []).filter((i) => i.section === s.key)}
                                            onSaved={() => {
                                                setEditing(null);
                                                reloadAll();
                                            }}
                                            onCancel={() => setEditing(null)}
                                            onReload={() => {
                                                setEditing(null);
                                                reloadAll();
                                            }}
                                        />
                                    ) : (
                                        <>
                                            {s.paragraphs.length === 0 && <p className="text-sm text-tertiary">Empty section.</p>}
                                            {s.paragraphs.map((p, i) => (
                                                <div key={i} className="flex flex-col gap-1.5">
                                                    {p.spans.map((sp) => (
                                                        <SpanView key={sp.span_id} span={sp} record={(records[s.key] ?? []).find((r) => r.span_id === sp.span_id)} projectId={pid} />
                                                    ))}
                                                </div>
                                            ))}
                                            {s.tables.map((t, ti) => (
                                                <TableView key={ti} sectionKey={s.key} index={ti} caption={t.caption} resultKeys={t.result_keys} issues={tableIssuesFor(s.key, ti, v.checks)} projectId={pid} />
                                            ))}
                                        </>
                                    )}
                                </section>
                            ))}
                        </div>
                        <aside className="flex flex-col gap-6" aria-label="Manuscript checks">
                            <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary" data-testid="unresolved-queue">
                                <h2 className="text-sm font-semibold text-primary">Unresolved-claim queue</h2>
                                <p className="text-xs text-tertiary">Factual sentences with no claim or result link.</p>
                                {(ms.data?.unresolved_claim_queue ?? []).length === 0 ? (
                                    <p className="text-sm text-tertiary">Empty.</p>
                                ) : (
                                    <ul className="flex flex-col gap-2">
                                        {ms.data!.unresolved_claim_queue!.map((q) => (
                                            <li key={q.span_id} className="text-sm">
                                                <a href={`#span-${q.span_id}`} className="text-secondary underline-offset-2 hover:underline">
                                                    {q.text}
                                                </a>
                                                <span className="block text-xs text-tertiary">{q.section}</span>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                            <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary" data-testid="table-issues">
                                <h2 className="text-sm font-semibold text-primary">Table issues</h2>
                                <p className="text-xs text-tertiary">Tables citing keys that are not committed results would compile with no rows; blockers stop completion.</p>
                                {(v.checks.table_issues ?? []).length === 0 ? (
                                    <p className="text-sm text-tertiary">None.</p>
                                ) : (
                                    <ul className="flex flex-col gap-2">
                                        {v.checks.table_issues!.map((i, n) => (
                                            <li key={n} className="text-sm">
                                                <a href={`#${tableAnchor(i.section, i.table_index)}`} className="text-secondary underline-offset-2 hover:underline">
                                                    Table “{i.caption}”: {i.message}
                                                </a>
                                                <span className="block text-xs text-tertiary">{i.section}</span>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                            <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary" data-testid="gap-sections">
                                <h2 className="text-sm font-semibold text-primary">Gap argument</h2>
                                <p className="text-xs text-tertiary">These sections must agree with your gap-resolution assessment.</p>
                                <ul className="flex flex-col gap-1">
                                    {Object.entries(ms.data?.gap_argument_sections_present ?? {}).map(([k, present]) => (
                                        <li key={k} className="flex items-center gap-2 text-sm">
                                            <StatusBadge status={present ? "complete" : "not_performed"} label={present ? "Written" : "Empty"} />
                                            {GAP_SECTION_LABEL[k] ?? k}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                            <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary" data-testid="bibliography">
                                <h2 className="text-sm font-semibold text-primary">Bibliography</h2>
                                <p className="text-xs text-tertiary">Only identity-verified papers that support a cited claim. The writer cannot add entries.</p>
                                {(ms.data?.bibliography ?? []).length === 0 ? (
                                    <p className="text-sm text-tertiary">No entries.</p>
                                ) : (
                                    <ul className="flex flex-col gap-2">
                                        {ms.data!.bibliography!.map((b) => (
                                            <li key={b.cite_key}>
                                                <details>
                                                    <summary className="cursor-pointer font-mono text-xs text-primary">{b.cite_key}</summary>
                                                    <pre className="mt-1 overflow-auto rounded bg-secondary p-2 text-xs whitespace-pre-wrap text-secondary">{b.bibtex}</pre>
                                                </details>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </aside>
                    </div>

                    <VersionsPanel projectId={pid} manuscriptId={m.id} tick={tick} />
                    <CompilePanel projectId={pid} templates={templates.data?.items ?? []} currentVersionId={v.id} canEdit={canEdit} onRequested={reloadAll} />
                </>
            )}

            <Section title="Manuscript completion" description="The manuscript.complete gate is evaluated by the server on the current committed version.">
                {gate ? (
                    <div data-testid="manuscript-gate" data-passed={gate.passed} className="flex flex-col gap-2">
                        <p className="flex items-center gap-2 text-sm">
                            <StatusBadge status={gate.passed ? "passed" : "blocked"} label={gate.passed ? "Complete" : "Not complete"} />
                        </p>
                        {gate.reasons.length > 0 && (
                            <ul className="list-disc pl-5 text-sm text-secondary">
                                {gate.reasons.map((r) => (
                                    <li key={r}>{r}</li>
                                ))}
                            </ul>
                        )}
                    </div>
                ) : (
                    <p className="text-sm text-tertiary">Evaluated while the project is in drafting (the project is in {project.state}).</p>
                )}
                <ErrorAlert error={advanceError} />
                {isOwner && project.state === "DRAFTING" && (
                    <div>
                        <Button
                            size="sm"
                            isLoading={advancing}
                            onClick={async () => {
                                setAdvancing(true);
                                setAdvanceError(undefined);
                                try {
                                    await api.post(`/v1/projects/${pid}/advance`, { requested_state: "SCIENTIFIC_REVIEW", expected_version: project.version });
                                    reloadAll();
                                } catch (err) {
                                    setAdvanceError(err);
                                } finally {
                                    setAdvancing(false);
                                }
                            }}
                        >
                            Move to scientific review
                        </Button>
                    </div>
                )}
            </Section>
        </div>
    );
}
