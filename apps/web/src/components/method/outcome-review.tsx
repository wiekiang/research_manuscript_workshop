"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ApprovalPanel } from "@/components/research/approval-panel";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { ApiError, api } from "@/lib/api/client";
import type { MatrixRowEntry, MatrixView } from "@/lib/api/types";
import { humanize } from "@/lib/format";

const OUTCOMES = ["supported", "partially_supported", "not_supported", "inconclusive"] as const;
export const GAP_STATUSES = ["addressed", "partially_addressed", "not_addressed", "inconclusive"] as const;

interface Props {
    projectId: string;
    matrix: MatrixView | undefined;
    isOwner: boolean;
    projectState: string;
    h3Declaration: string | undefined;
    onChanged: () => void;
}

/** Contribution validation matrix, gap-resolution assessment and H3. Draft rows must be reviewed by the researcher. */
export function OutcomeReview({ projectId, matrix, isOwner, projectState, h3Declaration, onChanged }: Props) {
    const [rows, setRows] = useState<MatrixRowEntry[]>([]);
    const [evidence, setEvidence] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [gapStatus, setGapStatus] = useState<string>("partially_addressed");
    const [gapIds, setGapIds] = useState("");
    const [gapExplanation, setGapExplanation] = useState("");
    const [gapError, setGapError] = useState<unknown>();
    const [gapBusy, setGapBusy] = useState(false);
    const [interpretation, setInterpretation] = useState("");
    const [limitations, setLimitations] = useState("");
    const [anomalies, setAnomalies] = useState(false);

    useEffect(() => {
        setRows(matrix?.items ?? []);
        setEvidence((matrix?.items ?? []).map((r) => r.evidence_ids.join(", ")));
        if (matrix?.gap_resolution) {
            setGapStatus(matrix.gap_resolution.status);
            setGapIds(matrix.gap_resolution.supporting_ids.join(", "));
            setGapExplanation(matrix.gap_resolution.explanation);
        }
    }, [matrix]);

    const update = (i: number, patch: Partial<MatrixRowEntry>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    const allReviewed = rows.length > 0 && rows.every((r) => r.origin === "researcher_reviewed");
    const overstated = gapError instanceof ApiError && gapError.code === "overstated";

    const h3Local: string[] = [];
    if (projectState !== "OUTCOME_REVIEW") h3Local.push(`H3 is recorded in outcome review (the project is in ${projectState})`);
    if (!allReviewed) h3Local.push("review every contribution-matrix row");
    if (!matrix?.gap_resolution) h3Local.push("record whether the work addressed the proposed gap");
    if (interpretation.trim().length < 40) h3Local.push("write your interpretation (at least 40 characters)");
    if (limitations.trim().length < 20) h3Local.push("state the limitations (at least 20 characters)");
    if (!anomalies) h3Local.push("confirm you reviewed anomalies");

    return (
        <div className="flex flex-col gap-10">
            <Section title="Contribution validation matrix" description={matrix?.note}>
                {rows.length === 0 && <p className="text-sm text-tertiary">No rows yet. Rows are drafted from the H1 direction once a method is selected.</p>}
                <ul className="flex flex-col gap-4">
                    {rows.map((r, i) => (
                        <li key={`${r.rq_index}-${i}`} data-testid="matrix-row" data-origin={r.origin} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm font-medium text-primary">RQ {r.rq_index}</span>
                                <StatusBadge status={r.origin === "researcher_reviewed" ? "confirmed" : "draft"} label={r.origin === "researcher_reviewed" ? "Reviewed by you" : "Draft (needs your review)"} />
                                {r.outcome && <StatusBadge status={`outcome_${r.outcome}`} />}
                            </div>
                            <p className="text-sm text-primary">{r.research_question}</p>
                            <p className="text-xs text-tertiary">Intended contribution: {r.intended_contribution}</p>
                            <p className="text-xs text-tertiary">Intended novelty: {r.intended_novelty}</p>
                            {isOwner && (
                                <>
                                    <Input label={`Success criterion (RQ ${r.rq_index})`} value={r.success_criterion} onChange={(v) => update(i, { success_criterion: v })} />
                                    <Input
                                        label={`Evidence IDs (RQ ${r.rq_index})`}
                                        hint="Result keys (RES-…) and claim keys (CLM-…) from this project."
                                        value={evidence[i] ?? ""}
                                        onChange={(v) => setEvidence((e) => e.map((x, j) => (j === i ? v : x)))}
                                    />
                                    <NativeSelect
                                        label={`Outcome (RQ ${r.rq_index})`}
                                        value={r.outcome ?? ""}
                                        onChange={(e) => update(i, { outcome: (e.target.value || null) as MatrixRowEntry["outcome"] })}
                                        options={[{ label: "Choose an outcome", value: "" }, ...OUTCOMES.map((o) => ({ label: humanize(o), value: o }))]}
                                    />
                                    <TextArea label={`Validity assessment (RQ ${r.rq_index})`} value={r.validity_assessment ?? ""} onChange={(v) => update(i, { validity_assessment: v })} rows={2} />
                                    <TextArea label={`Limitations (RQ ${r.rq_index})`} value={r.limitations ?? ""} onChange={(v) => update(i, { limitations: v })} rows={2} />
                                    <NativeSelect
                                        label={`H3 decision (RQ ${r.rq_index})`}
                                        value={r.h3_decision ?? ""}
                                        onChange={(e) => update(i, { h3_decision: (e.target.value || null) as MatrixRowEntry["h3_decision"] })}
                                        options={[
                                            { label: "Not decided", value: "" },
                                            { label: "Accepted", value: "accepted" },
                                            { label: "Revise", value: "revise" },
                                        ]}
                                    />
                                </>
                            )}
                        </li>
                    ))}
                </ul>
                <ErrorAlert error={error} />
                {isOwner && rows.length > 0 && (
                    <div>
                        <Button
                            size="sm"
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    await api.post(`/v1/projects/${projectId}/contribution-matrix/review`, {
                                        rows: rows.map((r, i) => ({
                                            rq_index: r.rq_index,
                                            research_question: r.research_question,
                                            intended_novelty: r.intended_novelty,
                                            intended_contribution: r.intended_contribution,
                                            success_criterion: r.success_criterion,
                                            evidence_ids: (evidence[i] ?? "").split(/[,\s]+/).map((x) => x.trim()).filter(Boolean),
                                            validity_assessment: r.validity_assessment,
                                            outcome: r.outcome,
                                            limitations: r.limitations,
                                            h3_decision: r.h3_decision,
                                        })),
                                    });
                                    onChanged();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Save my review of the matrix
                        </Button>
                    </div>
                )}
            </Section>
            <Section title="Did the work address the proposed gap?" description="Your overall assessment. The manuscript's abstract, introduction, discussion and conclusion must agree with it.">
                {matrix?.gap_resolution && (
                    <p data-testid="gap-recorded" className="text-sm text-secondary">
                        Recorded: <span className="font-medium">{humanize(matrix.gap_resolution.status)}</span> — {matrix.gap_resolution.explanation}
                    </p>
                )}
                {isOwner && (
                    <div className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
                        <NativeSelect label="Assessment" value={gapStatus} onChange={(e) => setGapStatus(e.target.value)} options={GAP_STATUSES.map((g) => ({ label: humanize(g), value: g }))} />
                        <Input label="Supporting IDs" value={gapIds} onChange={setGapIds} hint="Claim or result keys that support the assessment." />
                        <TextArea label="Explanation" isRequired hint="At least 20 characters." value={gapExplanation} onChange={setGapExplanation} rows={3} />
                        {overstated ? (
                            <p role="alert" data-testid="gap-overstated" className="rounded-xl bg-warning-primary p-3 text-sm text-secondary">
                                Refused as overstated: {(gapError as ApiError).message}
                            </p>
                        ) : (
                            <ErrorAlert error={gapError} />
                        )}
                        <div>
                            <Button
                                size="sm"
                                isLoading={gapBusy}
                                isDisabled={!allReviewed}
                                onClick={async () => {
                                    setGapBusy(true);
                                    setGapError(undefined);
                                    try {
                                        await api.post(`/v1/projects/${projectId}/gap-resolution`, {
                                            status: gapStatus,
                                            supporting_ids: gapIds.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean),
                                            explanation: gapExplanation,
                                        });
                                        onChanged();
                                    } catch (err) {
                                        setGapError(err);
                                    } finally {
                                        setGapBusy(false);
                                    }
                                }}
                            >
                                Record gap assessment
                            </Button>
                            {!allReviewed && <p className="mt-1 text-xs text-tertiary">Review every matrix row first.</p>}
                        </div>
                    </div>
                )}
            </Section>
            {isOwner && (
                <Section title="Outcome validation (H3)" description="Your validation of the actual outcomes, interpretation and limitations.">
                    <TextArea label="Interpretation" isRequired value={interpretation} onChange={setInterpretation} rows={3} />
                    <TextArea label="Limitations" isRequired value={limitations} onChange={setLimitations} rows={2} />
                    <Checkbox isSelected={anomalies} onChange={setAnomalies} label="I reviewed anomalies, exclusions and unexpected results" />
                    <ApprovalPanel
                        gate="H3"
                        title="Validate the outcomes"
                        declaration={h3Declaration ?? ""}
                        blockingReasons={h3Declaration ? h3Local : ["the H3 declaration could not be loaded", ...h3Local]}
                        submitLabel="Sign H3 and continue to drafting"
                        onSubmit={async (b) => {
                            await api.post(`/v1/projects/${projectId}/results/approve`, {
                                interpretation,
                                limitations,
                                anomalies_reviewed: anomalies,
                                declaration_accepted: b.declaration_accepted,
                                declaration_text: b.declaration_text,
                            });
                            onChanged();
                        }}
                    />
                </Section>
            )}
        </div>
    );
}
