"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { TextArea } from "@/components/base/textarea/textarea";
import { ApiError, api } from "@/lib/api/client";
import type { ExperimentPlanEntry, ExperimentRunEntry, Task } from "@/lib/api/types";
import { DATA_NATURE_LABEL, experimentHint, inputNatures, RUN_TYPE_LABEL, shortImage } from "@/lib/experiments";
import { formatDateTime, formatMoney, shortHash } from "@/lib/format";
import { RunCard } from "./run-card";

interface Props {
    projectId: string;
    plan: ExperimentPlanEntry;
    tasks: Task[];
    isOwner: boolean;
    canEdit: boolean;
    onChanged: () => void;
}

/** Approve (owner) with the exact declaration; the server checks the budget for an initial run plus a reproduction. */
function ApproveDialog({ projectId, plan, isOpen, onOpenChange, onApproved }: { projectId: string; plan: ExperimentPlanEntry; isOpen: boolean; onOpenChange: (o: boolean) => void; onApproved: () => void }) {
    const [accepted, setAccepted] = useState(false);
    const [rationale, setRationale] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const budget = error instanceof ApiError && error.code === "budget_exceeded";
    const hint = experimentHint(error);
    return (
        <DialogShell
            isOpen={isOpen}
            onOpenChange={onOpenChange}
            title={`Approve plan ${plan.plan_number}`}
            description="Only an approved plan of the frozen protocol can run. Approval budgets an initial run and one reproduction rerun."
            footer={
                <>
                    <Button color="secondary" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button
                        isLoading={busy}
                        isDisabled={!accepted}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(`/v1/experiment-plans/${plan.id}/approve`, {
                                    declaration_accepted: accepted,
                                    declaration_text: plan.declaration,
                                    rationale: rationale.trim() || null,
                                });
                                onOpenChange(false);
                                onApproved();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Approve plan
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <p data-testid="plan-declaration" className="rounded-lg bg-secondary p-3 text-sm text-primary">
                    {plan.declaration}
                </p>
                <Checkbox label="I accept this declaration" isSelected={accepted} onChange={setAccepted} />
                <TextArea label="Rationale (optional)" value={rationale} onChange={setRationale} rows={2} />
                <p className="text-xs text-tertiary">Estimated cost per run: {formatMoney(plan.estimate_cents)}</p>
                <ErrorAlert error={error} />
                {hint && <p className="text-sm text-tertiary">{hint}</p>}
                {budget && (
                    <Link href={`/projects/${projectId}/costs`} className="text-sm text-brand-secondary underline">
                        Open the Costs page to review the budget cap
                    </Link>
                )}
            </div>
        </DialogShell>
    );
}

export function PlanCard({ projectId, plan, tasks, isOwner, canEdit, onChanged }: Props) {
    const [approveOpen, setApproveOpen] = useState(false);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<unknown>();
    const natures = inputNatures(plan.spec.inputs);
    const hint = experimentHint(error);

    const start = async (rerunOf?: ExperimentRunEntry) => {
        setBusy(rerunOf?.id ?? "new");
        setError(undefined);
        try {
            await api.post(`/v1/experiment-plans/${plan.id}/runs`, { rerun_of: rerunOf?.id ?? null });
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(null);
        }
    };

    return (
        <article data-testid="experiment-plan" data-status={plan.status} className="flex flex-col gap-4 rounded-2xl border border-secondary p-5">
            <header className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-md font-semibold text-primary">
                        Plan {plan.plan_number}: {plan.title}
                    </h3>
                    <StatusBadge status={`plan_${plan.status}`} />
                    <span data-testid="plan-run-type">
                        <StatusBadge status={`run_${plan.run_type}`} label={RUN_TYPE_LABEL[plan.run_type]} />
                    </span>
                    {natures.map((n) => (
                        <span key={n} data-testid="plan-data-nature" data-nature={n}>
                            <StatusBadge status={`data_${n}`} label={`${DATA_NATURE_LABEL[n]} data`} />
                        </span>
                    ))}
                </div>
                {plan.synthetic && (
                    <p data-testid="plan-synthetic" className="text-sm text-warning-primary">
                        Some inputs are synthetic or simulated. Results from this plan are labelled as such and cannot stand in for empirical findings.
                    </p>
                )}
                {plan.run_type === "exploratory" && (
                    <p className="text-sm text-tertiary">Exploratory: do not present results from this plan as confirmatory evidence.</p>
                )}
            </header>

            <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div>
                    <dt className="text-xs text-tertiary">Image (pinned)</dt>
                    <dd className="font-mono text-xs break-all text-primary" title={plan.image_ref}>
                        {plan.spec.image} · {shortImage(plan.image_ref)}
                    </dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Command</dt>
                    <dd className="font-mono text-xs break-all text-primary">{plan.spec.entrypoint.join(" ")} (seed {plan.spec.seed})</dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Code hash</dt>
                    <dd className="font-mono text-xs break-all text-primary" title={plan.code_hash}>
                        {shortHash(plan.code_hash, 16)}
                    </dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Frozen protocol hash</dt>
                    <dd className="font-mono text-xs break-all text-primary" title={plan.protocol_hash}>
                        {shortHash(plan.protocol_hash, 16)}
                    </dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Limits</dt>
                    <dd className="text-xs text-primary">
                        {plan.spec.limits.cpus} CPU · {plan.spec.limits.memory_mb} MB · {plan.spec.limits.timeout_s} s · no network
                    </dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Estimated cost per run</dt>
                    <dd className="text-xs text-primary">{formatMoney(plan.estimate_cents)}</dd>
                </div>
            </dl>
            {Object.keys(plan.input_hashes).length > 0 && (
                <ul data-testid="plan-inputs" className="flex flex-col gap-1 text-xs">
                    {plan.spec.inputs.map((i) => (
                        <li key={i.path} className="flex flex-wrap gap-2">
                            <span className="font-mono text-secondary">{i.path}</span>
                            <span className="text-tertiary">{DATA_NATURE_LABEL[i.data_nature]}</span>
                            <span className="font-mono text-tertiary" title={plan.input_hashes[i.path]}>
                                {shortHash(plan.input_hashes[i.path], 16)}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
            <p className="text-xs text-tertiary">
                Rerun command: <span className="font-mono">{plan.rerun_command}</span>
            </p>
            <div className="flex flex-wrap items-center gap-3">
                <ArtifactLink artifactId={plan.artifact_id} label="Plan record" />
                {plan.approved_at && <span className="text-xs text-tertiary">Approved {formatDateTime(plan.approved_at)}</span>}
            </div>

            <div className="flex flex-wrap gap-2">
                {plan.status === "draft" && isOwner && (
                    <Button size="sm" onClick={() => setApproveOpen(true)}>
                        Review and approve
                    </Button>
                )}
                {plan.status === "draft" && !isOwner && <p className="text-sm text-tertiary">Waiting for the project owner to approve this plan.</p>}
                {plan.status === "approved" && canEdit && (
                    <Button size="sm" color="secondary" isLoading={busy === "new"} onClick={() => start()}>
                        Start run
                    </Button>
                )}
            </div>
            <ErrorAlert error={error} />
            {hint && <p className="text-sm text-tertiary">{hint}</p>}

            {plan.runs.length > 0 && (
                <div className="flex flex-col gap-3">
                    <h4 className="text-sm font-semibold text-secondary">Runs</h4>
                    {plan.runs.map((r) => (
                        <RunCard
                            key={r.id}
                            projectId={projectId}
                            run={r}
                            task={tasks.find((t) => t.id === r.task_id)}
                            canEdit={canEdit}
                            onChanged={onChanged}
                            onRerun={(run) => start(run)}
                            rerunBusy={busy === r.id}
                        />
                    ))}
                </div>
            )}
            <ApproveDialog projectId={projectId} plan={plan} isOpen={approveOpen} onOpenChange={setApproveOpen} onApproved={onChanged} />
        </article>
    );
}
