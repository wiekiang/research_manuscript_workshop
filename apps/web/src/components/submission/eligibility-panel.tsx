"use client";

import { useState } from "react";
import { Plus, Trash01 } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { ErrorAlert } from "@/components/research/error-alert";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { DeadlineRow, EligibilityResult } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import { ELIGIBILITY_LABEL, INTENDED_ACTIONS, eligibilityStatusKey } from "@/lib/submission";

function DeadlineTable({ rows, testId, empty }: { rows: DeadlineRow[]; testId: string; empty: string }) {
    if (rows.length === 0) return <p className="text-sm text-tertiary">{empty}</p>;
    return (
        <ul data-testid={testId} className="flex flex-col gap-1 text-sm">
            {rows.map((d) => (
                <li key={`${testId}-${d.id}`} data-kind={d.kind} className="flex flex-wrap gap-2 text-secondary">
                    <span className="font-medium text-primary">{humanize(d.kind)}</span>
                    <span>{d.due_at ? formatDateTime(d.due_at) : "date not resolved"}</span>
                    <span className="text-tertiary">{d.timezone ? `stated time zone ${d.timezone}` : "time zone not stated"}</span>
                    {d.mandatory != null && <span className="text-tertiary">{d.mandatory ? "mandatory" : "optional"}</span>}
                    {d.note && <span className="text-tertiary">— {d.note}</span>}
                </li>
            ))}
        </ul>
    );
}

/**
 * Result of the versioned deadline policy evaluator for one intended action. Only deadlines that govern the action
 * decide eligibility; passed deadlines unrelated to it are shown as context, never as "ineligible".
 */
export function EligibilityResultView({ result }: { result: EligibilityResult }) {
    return (
        <div data-testid="eligibility-result" data-status={result.status} className="flex flex-col gap-4 rounded-xl border border-secondary p-4">
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={eligibilityStatusKey(result.status)} label={ELIGIBILITY_LABEL[result.status] ?? result.status} />
                <span className="text-sm text-secondary">Action: {INTENDED_ACTIONS.find((a) => a.value === result.action)?.label ?? result.action}</span>
                <span className="text-xs text-tertiary">
                    Evaluated {formatDateTime(result.evaluated_at)} by {result.evaluator}
                </span>
            </div>
            {result.reasons.length > 0 && (
                <ul data-testid="eligibility-reasons" className="list-disc pl-5 text-sm text-secondary">
                    {result.reasons.map((r) => (
                        <li key={r}>{r}</li>
                    ))}
                </ul>
            )}
            <div className="flex flex-col gap-1">
                <h4 className="text-xs font-semibold text-secondary">Deadlines that govern this action</h4>
                <DeadlineTable rows={result.governing} testId="eligibility-governing" empty="No recorded deadline governs this action." />
            </div>
            <div className="flex flex-col gap-1">
                <h4 className="text-xs font-semibold text-secondary">Prerequisites still to complete</h4>
                <DeadlineTable rows={result.pending_prerequisites} testId="eligibility-pending" empty="None outstanding." />
            </div>
            <div className="flex flex-col gap-1">
                <h4 className="text-xs font-semibold text-secondary">Context: passed deadlines that do not govern this action</h4>
                <DeadlineTable rows={result.context} testId="eligibility-context" empty="None." />
            </div>
        </div>
    );
}

export function EligibilityForm({ projectId, canEdit, onResult }: { projectId: string; canEdit: boolean; onResult: (r: EligibilityResult) => void }) {
    const [action, setAction] = useState("new_submission");
    const [prereqs, setPrereqs] = useState<{ kind: string; reference: string }[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <div className="flex flex-col gap-3">
            <NativeSelect label="Intended next action" value={action} onChange={(e) => setAction(e.target.value)} options={INTENDED_ACTIONS} />
            <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium text-secondary">Completed prerequisites (your attestation)</legend>
                <p className="text-xs text-tertiary">For example, a completed abstract registration with its confirmation ID from the venue's system.</p>
                {prereqs.map((p, i) => (
                    <div key={i} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
                        <NativeSelect
                            label={`Prerequisite ${i + 1}`}
                            value={p.kind}
                            onChange={(e) => setPrereqs((xs) => xs.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}
                            options={[
                                { value: "abstract_registration", label: "Abstract registration" },
                                { value: "author_registration", label: "Author registration" },
                            ]}
                        />
                        <Input label={`Reference ${i + 1}`} value={p.reference} onChange={(v) => setPrereqs((xs) => xs.map((x, j) => (j === i ? { ...x, reference: v } : x)))} />
                        <Button size="sm" color="secondary-destructive" iconLeading={Trash01} aria-label={`Remove prerequisite ${i + 1}`} onClick={() => setPrereqs((xs) => xs.filter((_, j) => j !== i))}>
                            Remove
                        </Button>
                    </div>
                ))}
                <div>
                    <Button size="sm" color="secondary" iconLeading={Plus} onClick={() => setPrereqs((xs) => [...xs, { kind: "abstract_registration", reference: "" }])}>
                        Add completed prerequisite
                    </Button>
                </div>
            </fieldset>
            <ErrorAlert error={error} />
            {canEdit && (
                <div>
                    <Button
                        size="sm"
                        isLoading={busy}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                onResult(await api.post<EligibilityResult>(`/v1/projects/${projectId}/eligibility`, { intended_action: action, completed_prerequisites: prereqs }));
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Evaluate eligibility
                    </Button>
                </div>
            )}
        </div>
    );
}
