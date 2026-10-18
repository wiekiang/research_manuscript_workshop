import { StatusBadge } from "@/components/research/status-badge";
import type { ClaimCheck } from "@/lib/api/types";
import { VERDICT_LABEL } from "@/lib/review";

const METHOD_LABEL: Record<string, string> = {
    deterministic: "Deterministic source check",
    "deterministic+model_assisted": "Deterministic source check + model-assisted meaning check",
};

/** Every critical claim/evidence pair and the documented sample of noncritical claims, with what was not checked. */
export function ClaimChecks({ checks, samplingRule, summary }: { checks: ClaimCheck[]; samplingRule: { id: string; description: string }; summary?: Record<string, unknown> }) {
    const unchecked = (summary?.unchecked_noncritical as string[] | undefined) ?? [];
    return (
        <div className="flex flex-col gap-3" data-testid="claim-checks">
            <p className="text-sm text-secondary">
                Sampling rule <span className="font-mono">{samplingRule.id}</span>: {samplingRule.description}
            </p>
            <p className="text-sm text-secondary" data-testid="unchecked-noncritical">
                Unchecked noncritical claims: {unchecked.length === 0 ? "none" : unchecked.join(", ")}
            </p>
            {checks.length === 0 ? (
                <p className="text-sm text-tertiary">No claim was checked in this round.</p>
            ) : (
                <ul className="flex flex-col gap-2">
                    {checks.map((c) => (
                        <li key={c.claim_key} data-testid="claim-check" data-claim={c.claim_key} className="flex flex-col gap-2 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="font-mono text-sm text-primary">{c.claim_key}</span>
                                <span className="text-xs text-secondary">{c.selection === "critical" ? "Critical (always checked)" : "Sampled noncritical"}</span>
                                <StatusBadge status={["passed", "failed"].includes(c.source_status) ? c.source_status : "not_performed"} label={`Source: ${c.source_status.replace(/_/g, " ")}`} />
                                <span className="text-xs text-tertiary">{METHOD_LABEL[c.method] ?? c.method}</span>
                                {c.reused && <span className="text-xs text-tertiary">Reused prior check (claim, source and sentences unchanged)</span>}
                            </div>
                            <p className="text-xs text-tertiary">{c.source_detail}</p>
                            {c.meaning.length > 0 && (
                                <ul className="flex flex-col gap-1">
                                    {c.meaning.map((m) => (
                                        <li key={m.span_id} className="flex flex-wrap items-center gap-2 text-xs" data-testid="span-verdict" data-verdict={m.verdict}>
                                            <span className="font-mono text-secondary">{m.span_id}</span>
                                            <StatusBadge status={m.verdict === "not_performed" ? "not_performed" : `verdict_${m.verdict}`} label={VERDICT_LABEL[m.verdict] ?? m.verdict} />
                                            <span className="text-tertiary">{m.rationale}</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}
