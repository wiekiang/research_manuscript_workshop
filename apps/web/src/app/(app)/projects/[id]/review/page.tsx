"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { TaskProgress } from "@/components/cfp/task-progress";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { ClaimChecks } from "@/components/review/claim-checks";
import { CompliancePanel } from "@/components/review/compliance-panel";
import { FindingsPanel } from "@/components/review/findings-panel";
import { GatePanel } from "@/components/review/gate-panel";
import { MetaReviewPanel, ReportCards } from "@/components/review/report-cards";
import { RevisionPanel } from "@/components/review/revision-panel";
import { useResource } from "@/hooks/use-resource";
import { api, newIdempotencyKey } from "@/lib/api/client";
import type { ReviewsView, Task } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { FUNCTION_LABEL, FUNCTION_ORDER, openBlocking, refusalHint } from "@/lib/review";

const ACTIVE = ["queued", "running", "failed_retryable"];

export default function ReviewPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const reviews = useResource<ReviewsView>(pid ? `/v1/projects/${pid}/reviews` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const [fns, setFns] = useState<string[]>([...FUNCTION_ORDER]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const reviewTasks = (tasks.data?.items ?? []).filter((t) => t.kind === "review_run" || (t.kind === "manuscript_generation" && String(t.params?.instructions ?? "").includes("review findings")));
    const active = reviewTasks.some((t) => ACTIVE.includes(t.state));
    const reloadAll = () => void Promise.all([reviews.reload(), tasks.reload(), reload()]);

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
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    const data = reviews.data;
    const latest = data?.items[0];
    const isCurrent = latest && data?.current_version_id === latest.manuscript_version_id;
    const blocking = openBlocking(latest?.findings ?? []);
    const hint = refusalHint(error);

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Independent review"
                description="Separate review functions examine one committed manuscript version and freeze their reports before a meta-review consolidates them. Review is diagnostic: there is no score and no prediction of acceptance."
            >
                {canEdit && (
                    <div className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
                        <fieldset className="flex flex-col gap-2">
                            <legend className="mb-1 text-sm font-medium text-secondary">Functions to run</legend>
                            {FUNCTION_ORDER.map((f) => (
                                <Checkbox key={f} isSelected={fns.includes(f)} onChange={(v) => setFns((x) => (v ? [...x, f] : x.filter((y) => y !== f)))} label={FUNCTION_LABEL[f]} />
                            ))}
                        </fieldset>
                        <div>
                            <Button
                                size="sm"
                                isLoading={busy}
                                isDisabled={fns.length === 0}
                                onClick={async () => {
                                    setBusy(true);
                                    setError(undefined);
                                    try {
                                        await api.post(`/v1/projects/${pid}/reviews`, { functions: fns }, newIdempotencyKey("review"));
                                        reloadAll();
                                    } catch (err) {
                                        setError(err);
                                    } finally {
                                        setBusy(false);
                                    }
                                }}
                            >
                                Run review on the current version
                            </Button>
                        </div>
                        <ErrorAlert error={error} />
                        {hint && <p className="text-sm text-tertiary">{hint}</p>}
                    </div>
                )}
                {reviews.isLoading && !data && <Loading label="Loading reviews" />}
                <ErrorAlert error={reviews.error} />
                {data && data.items.length === 0 && (
                    <p data-testid="review-empty" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        No review has run yet. Reviews run on a complete manuscript, once the project is in scientific review.
                    </p>
                )}
            </Section>

            <TaskProgress tasks={reviewTasks} title="Review tasks" onChanged={reloadAll} />

            {latest && data && (
                <>
                    <Section title={`Review of manuscript version ${latest.manuscript_version}`} description={`Requested ${formatDateTime(latest.created_at)}.`}>
                        <div className="flex flex-wrap items-center gap-3" data-testid="latest-round" data-status={latest.status}>
                            <StatusBadge status={`round_${latest.status}`} />
                            {!isCurrent && (
                                <StatusBadge status="stale" label="Older version: gates use only a review of the current version" />
                            )}
                            <span className="text-sm text-secondary">
                                {blocking.length} open blocker/major finding(s) in the scientific, citation/evidence and technical reviews.
                            </span>
                        </div>
                        <ReportCards reports={latest.reports} functions={latest.functions} />
                    </Section>

                    <Section title="Meta-review" description="Consolidates the frozen reports and highlights where reviewers disagree.">
                        <MetaReviewPanel meta={latest.meta} />
                    </Section>

                    <Section title="Findings" description="Severity, the sentences, claims and artifacts concerned, the reproducible check and a proposed fix. Only a researcher resolves findings.">
                        <FindingsPanel projectId={pid} findings={latest.findings ?? []} canEdit={canEdit} onChanged={reloadAll} />
                    </Section>

                    {latest.functions.includes("citation_evidence") && (
                        <Section title="Claim and evidence checks" description="The citation reviewer opens the stored source for every critical claim and a documented sample of noncritical claims, then checks every linked sentence.">
                            <ClaimChecks checks={latest.claim_checks ?? []} samplingRule={data.sampling_rule} summary={latest.reports.find((r) => r.function === "citation_evidence")?.summary} />
                        </Section>
                    )}

                    <Section title="Automatic revision" description="Diagnostic findings can seed a draft revision of the affected sections.">
                        <RevisionPanel projectId={pid} round={latest} cycles={data.revision_cycles} canEdit={canEdit} onRequested={reloadAll} />
                    </Section>

                    <Section title="Venue compliance" description="Read directly from the official CFP snapshot and the compile run of this version. Manual checks need a signed decision.">
                        <CompliancePanel round={latest} declaration={data.decision_declaration} canEdit={canEdit} onChanged={reloadAll} />
                    </Section>

                    {data.items.length > 1 && (
                        <Section title="Earlier review rounds">
                            <ul className="flex flex-col gap-2" data-testid="earlier-rounds">
                                {data.items.slice(1).map((r) => (
                                    <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm text-secondary">
                                        <StatusBadge status={`round_${r.status}`} />
                                        Version {r.manuscript_version} · {formatDateTime(r.created_at)} · {r.reports.length} frozen report(s)
                                    </li>
                                ))}
                            </ul>
                        </Section>
                    )}
                </>
            )}

            <Section title="Scientific review gate" description="review.passed: the independent review of the current version is complete and has no open blocker or major finding.">
                <GatePanel project={project} fromState="SCIENTIFIC_REVIEW" toState="COMPLIANCE_REVIEW" gateIds={["review.passed"]} onAdvanced={reloadAll} />
            </Section>
            <Section title="Compliance and integrity gate" description="compliance.checked and integrity.checked (plus the pre-approval readiness assessment) before final approval.">
                <GatePanel project={project} fromState="COMPLIANCE_REVIEW" toState="FINAL_APPROVAL" gateIds={["compliance.checked", "integrity.checked", "readiness.pre_approval"]} onAdvanced={reloadAll} />
                <p className="text-sm text-tertiary">
                    Integrity checks are on the{" "}
                    <a href={`/projects/${pid}/integrity`} className="text-brand-secondary underline-offset-2 hover:underline">
                        research integrity page
                    </a>
                    .
                </p>
            </Section>
        </div>
    );
}
