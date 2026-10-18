"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { NativeSelect } from "@/components/base/select/select-native";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { ReviewRecord, ReviewSpec, ScreeningState } from "@/lib/api/types";
import { exclusionOptions } from "@/lib/synthesis";
import { Refusal } from "./refusal";

type Stage = "title_abstract" | "full_text";

function DecisionLabel({ d }: { d: ScreeningState | null }) {
    if (!d) return <span className="text-xs text-tertiary">No decision</span>;
    return (
        <span className="flex flex-col gap-0.5">
            <StatusBadge status={d.decision === "include" ? "screen_included" : "screen_excluded"} label={d.decision === "include" ? "Included" : "Excluded"} />
            {d.decision === "exclude" && d.reason && <span className="text-xs text-secondary">Reason: {d.reason}</span>}
            <span className="text-xs text-tertiary">Human decision ({d.method})</span>
        </span>
    );
}

/** Screening controls for one record and stage; an exclusion can only use a reason frozen in the protocol. */
export function ScreeningControl({ projectId, record, stage, spec, onDone }: { projectId: string; record: ReviewRecord; stage: Stage; spec: ReviewSpec; onDone: () => void }) {
    const reasons = exclusionOptions(spec);
    const [reason, setReason] = useState(reasons[0] ?? "");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const label = stage === "title_abstract" ? "title/abstract" : "full text";
    const decide = async (decision: "include" | "exclude") => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/review/screening`, {
                paper_id: record.paper_id,
                stage,
                decision,
                reason: decision === "exclude" ? reason : null,
            });
            onDone();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };
    return (
        <div className="flex flex-col gap-2" data-testid={`screen-${stage}`}>
            <div className="flex flex-wrap items-end gap-2">
                <Button size="sm" color="secondary" isLoading={busy} onClick={() => decide("include")} aria-label={`Include at ${label}: ${record.title ?? record.paper_id}`}>
                    Include
                </Button>
                <NativeSelect
                    label={`Exclusion reason (${label})`}
                    size="sm"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    options={reasons.map((r) => ({ label: r, value: r }))}
                />
                <Button size="sm" color="secondary-destructive" isDisabled={!reason} onClick={() => decide("exclude")} aria-label={`Exclude at ${label}: ${record.title ?? record.paper_id}`}>
                    Exclude
                </Button>
            </div>
            <Refusal error={error} />
        </div>
    );
}

interface Props {
    projectId: string;
    records: ReviewRecord[];
    spec: ReviewSpec;
    includedIds: string[];
    canEdit: boolean;
    onChanged: () => void;
    onExtract: (r: ReviewRecord) => void;
}

/** Records of the protocol's searches. Screening is a human decision; no model output is shown as a decision. */
export function RecordsTable({ projectId, records, spec, includedIds, canEdit, onChanged, onExtract }: Props) {
    if (records.length === 0) return <p className="text-sm text-tertiary">No records yet. Run the specified searches.</p>;
    return (
        <div className="overflow-x-auto rounded-xl ring-1 ring-secondary">
            <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="bg-secondary text-xs text-tertiary">
                    <tr>
                        <th className="px-3 py-2 font-medium">Record</th>
                        <th className="px-3 py-2 font-medium">Title/abstract</th>
                        <th className="px-3 py-2 font-medium">Full text</th>
                        <th className="px-3 py-2 font-medium">Extraction</th>
                    </tr>
                </thead>
                <tbody>
                    {records.map((r) => {
                        const included = includedIds.includes(r.paper_id);
                        const taIncluded = r.title_abstract?.decision === "include";
                        return (
                            <tr key={r.paper_id} data-testid="review-record" data-paper={r.paper_id} className="border-t border-secondary align-top">
                                <td className="px-3 py-2">
                                    <p className="font-medium text-primary">{r.title ?? "Untitled record"}</p>
                                    {r.doi && <p className="text-xs text-tertiary">doi:{r.doi}</p>}
                                </td>
                                <td className="px-3 py-2">
                                    <div className="flex flex-col gap-2">
                                        <DecisionLabel d={r.title_abstract} />
                                        {canEdit && <ScreeningControl projectId={projectId} record={r} stage="title_abstract" spec={spec} onDone={onChanged} />}
                                    </div>
                                </td>
                                <td className="px-3 py-2">
                                    <div className="flex flex-col gap-2">
                                        <DecisionLabel d={r.full_text} />
                                        {canEdit && taIncluded && <ScreeningControl projectId={projectId} record={r} stage="full_text" spec={spec} onDone={onChanged} />}
                                        {!taIncluded && <span className="text-xs text-tertiary">Assessed only after inclusion at title/abstract</span>}
                                    </div>
                                </td>
                                <td className="px-3 py-2">
                                    {included ? (
                                        <div className="flex flex-col gap-1">
                                            <StatusBadge status={r.extracted ? "extraction_recorded" : "extraction_missing"} label={r.extracted ? "Recorded" : "Not yet extracted"} />
                                            {canEdit && (
                                                <Button size="sm" color="link-color" onClick={() => onExtract(r)}>
                                                    {r.extracted ? "Record again" : "Extract and appraise"}
                                                </Button>
                                            )}
                                        </div>
                                    ) : (
                                        <span className="text-xs text-tertiary">Only included studies</span>
                                    )}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
