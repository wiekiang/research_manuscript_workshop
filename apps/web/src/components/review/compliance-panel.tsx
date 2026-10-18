"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { StatusBadge } from "@/components/research/status-badge";
import type { ComplianceCheck, ReviewRound } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { checkStatusKey } from "@/lib/review";
import { DecisionDialog } from "./decision-dialog";

/** Checks read directly from the official CFP snapshot, the confirmed template and the compile run of this version. */
export function CompliancePanel({ round, declaration, canEdit, onChanged }: { round: ReviewRound; declaration: string; canEdit: boolean; onChanged: () => void }) {
    const [deciding, setDeciding] = useState<ComplianceCheck | null>(null);
    const report = round.reports.find((r) => r.function === "compliance");
    if (!report) return <p className="text-sm text-tertiary">This round did not include the venue-compliance review.</p>;
    const checks = (report.summary.checks ?? []) as ComplianceCheck[];
    const decisions = new Map((round.compliance_decisions ?? []).map((d) => [d.check_id, d]));
    return (
        <div className="flex flex-col gap-2" data-testid="compliance-checks">
            {checks.length === 0 && <p className="text-sm text-tertiary">No compliance checks were recorded.</p>}
            <ul className="flex flex-col gap-2">
                {checks.map((c) => {
                    const d = decisions.get(c.id);
                    return (
                        <li key={c.id} data-testid="compliance-check" data-check={c.id} data-status={c.status} className="flex flex-col gap-1 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="font-mono text-sm text-primary">{c.id}</span>
                                <StatusBadge status={checkStatusKey(c.status)} />
                                {!c.blocking && <span className="text-xs text-tertiary">Not blocking</span>}
                            </div>
                            <p className="text-sm text-secondary">{c.detail}</p>
                            {c.quote && <blockquote className="border-l-2 border-secondary pl-3 text-xs text-tertiary">“{c.quote}”</blockquote>}
                            {c.source && (
                                <a href={c.source} target="_blank" rel="noreferrer noopener" className="text-xs break-all text-brand-secondary underline-offset-2 hover:underline">
                                    Official source: {c.source}
                                </a>
                            )}
                            {d && (
                                <p className="text-xs text-tertiary" data-testid="compliance-decision">
                                    Signed decision: {d.decision.replace(/_/g, " ")} — {d.rationale} · {formatDateTime(d.at)}
                                </p>
                            )}
                            {canEdit && c.status === "manual_check" && !d && (
                                <div>
                                    <Button size="sm" color="secondary" onClick={() => setDeciding(c)}>
                                        Record signed decision
                                    </Button>
                                </div>
                            )}
                        </li>
                    );
                })}
            </ul>
            {deciding && (
                <DecisionDialog
                    isOpen
                    onOpenChange={(o) => !o && setDeciding(null)}
                    path={`/v1/reviews/${round.id}/compliance/${encodeURIComponent(deciding.id)}/decide`}
                    checkId={deciding.id}
                    detail={deciding.detail}
                    declaration={declaration}
                    onDone={onChanged}
                />
            )}
        </div>
    );
}
