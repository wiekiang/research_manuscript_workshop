"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { ReviewFinding } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import { FUNCTION_LABEL, RESOLUTION_LABEL, SEVERITY_LABEL, groupFindings, refusalHint, resolutionOptions } from "@/lib/review";

export function FindingsPanel({ projectId, findings, canEdit, onChanged }: { projectId: string; findings: ReviewFinding[]; canEdit: boolean; onChanged: () => void }) {
    const [resolving, setResolving] = useState<ReviewFinding | null>(null);
    const groups = groupFindings(findings);
    if (findings.length === 0) return <p className="text-sm text-tertiary">No findings were reported in this round.</p>;
    return (
        <div className="flex flex-col gap-6" data-testid="findings">
            {groups.map((g) => (
                <section key={g.fn} aria-labelledby={`findings-${g.fn}`} data-testid="finding-group" data-function={g.fn} className="flex flex-col gap-3">
                    <h3 id={`findings-${g.fn}`} className="text-md font-semibold text-primary">
                        {FUNCTION_LABEL[g.fn] ?? g.fn}
                    </h3>
                    {g.bySeverity.map((s) => (
                        <div key={s.severity} className="flex flex-col gap-2">
                            <h4 className="text-sm font-medium text-secondary">
                                {SEVERITY_LABEL[s.severity]} ({s.items.length})
                            </h4>
                            <ul className="flex flex-col gap-2">
                                {s.items.map((f) => (
                                    <FindingRow key={f.id} f={f} projectId={projectId} canEdit={canEdit} onResolve={() => setResolving(f)} />
                                ))}
                            </ul>
                        </div>
                    ))}
                </section>
            ))}
            {resolving && <ResolveDialog finding={resolving} onClose={() => setResolving(null)} onDone={onChanged} />}
        </div>
    );
}

function FindingRow({ f, projectId, canEdit, onResolve }: { f: ReviewFinding; projectId: string; canEdit: boolean; onResolve: () => void }) {
    return (
        <li data-testid="finding" data-severity={f.severity} data-status={f.status} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-secondary px-1.5 py-0.5 text-xs font-semibold text-primary">{SEVERITY_LABEL[f.severity]}</span>
                <span className="text-sm font-medium text-primary">{f.title}</span>
                <StatusBadge status={`finding_${f.status}`} label={RESOLUTION_LABEL[f.status] ?? f.status} />
                <span className="text-xs text-tertiary">{humanize(f.category)}</span>
            </div>
            <p className="text-sm text-secondary">{f.rationale}</p>
            <dl className="grid gap-1 text-xs text-tertiary sm:grid-cols-[8rem_1fr]">
                <dt>Reproducible check</dt>
                <dd className="text-secondary">{f.check}</dd>
                {f.proposed_fix && (
                    <>
                        <dt>Proposed fix</dt>
                        <dd className="text-secondary" data-testid="proposed-fix">{f.proposed_fix}</dd>
                    </>
                )}
                {f.span_ids.length > 0 && (
                    <>
                        <dt>Sentences</dt>
                        <dd className="flex flex-wrap gap-2">
                            {f.span_ids.map((s) => (
                                <a key={s} href={`/projects/${projectId}/manuscript#span-${s}`} className="font-mono text-brand-secondary underline-offset-2 hover:underline">
                                    {s}
                                </a>
                            ))}
                        </dd>
                    </>
                )}
                {f.claim_ids.length > 0 && (
                    <>
                        <dt>Claims</dt>
                        <dd className="font-mono text-secondary">{f.claim_ids.join(", ")}</dd>
                    </>
                )}
                {f.artifact_ids.length > 0 && (
                    <>
                        <dt>Artifacts</dt>
                        <dd className="font-mono break-all text-secondary">{f.artifact_ids.join(", ")}</dd>
                    </>
                )}
                {f.rule_ids.length > 0 && (
                    <>
                        <dt>CFP rules</dt>
                        <dd className="font-mono break-all text-secondary">{f.rule_ids.join(", ")}</dd>
                    </>
                )}
            </dl>
            {f.status !== "open" && f.resolution_note && (
                <p className="text-xs text-tertiary" data-testid="resolution-note">
                    {RESOLUTION_LABEL[f.status]}: {f.resolution_note}
                    {f.resolved_at && ` · ${formatDateTime(f.resolved_at)}`}
                    {f.resolved_in_version != null && ` · manuscript v${f.resolved_in_version}`}
                </p>
            )}
            {canEdit && f.status === "open" && (
                <div>
                    <Button size="sm" color="secondary" onClick={onResolve}>
                        Resolve finding
                    </Button>
                </div>
            )}
        </li>
    );
}

function ResolveDialog({ finding, onClose, onDone }: { finding: ReviewFinding; onClose: () => void; onDone: () => void }) {
    const opts = resolutionOptions(finding);
    const [resolution, setResolution] = useState(opts[0].value);
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const hint = refusalHint(error);
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Resolve review finding"
            description={`${SEVERITY_LABEL[finding.severity]} · ${finding.title}. Only researchers resolve findings; the server checks every rule.`}
            footer={
                <>
                    <Button size="sm" color="secondary" onClick={onClose}>
                        Close
                    </Button>
                    <Button
                        size="sm"
                        isLoading={busy}
                        isDisabled={!note.trim()}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(`/v1/review-findings/${finding.id}/resolve`, { resolution, note });
                                onDone();
                                onClose();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Record resolution
                    </Button>
                </>
            }
        >
            <NativeSelect label="Resolution" value={resolution} onChange={(e) => setResolution(e.target.value)} options={opts} />
            {finding.severity === "blocker" && <p className="text-xs text-tertiary">A blocker cannot be accepted as a risk.</p>}
            <TextArea label="Note (for accepted risk or rejection: your reason, at least 20 characters)" value={note} onChange={setNote} rows={3} />
            <ErrorAlert error={error} />
            {hint && (
                <p className="text-sm text-tertiary" data-testid="refusal-hint">
                    {hint}
                </p>
            )}
        </DialogShell>
    );
}
