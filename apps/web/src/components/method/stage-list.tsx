import { StatusBadge } from "@/components/research/status-badge";
import type { StageDefinitionEntry } from "@/lib/api/types";

/** Required method stages in order, with their deterministic validator results. */
export function StageList({ stages }: { stages: StageDefinitionEntry[] }) {
    if (stages.length === 0) return <p className="text-sm text-tertiary">No stages defined.</p>;
    return (
        <ol className="flex flex-col gap-2">
            {stages.map((s, i) => (
                <li key={s.id} data-testid="method-stage" data-status={s.status} className="flex flex-col gap-1 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-primary">
                            {i + 1}. {s.title}
                        </span>
                        <StatusBadge status={`stage_${s.status}`} />
                        {s.predecessor_stage_ids.length > 0 && <span className="text-xs text-tertiary">after {s.predecessor_stage_ids.join(", ")}</span>}
                    </div>
                    <p className="text-xs text-tertiary">{s.description}</p>
                    {s.validator_results.length > 0 && (
                        <ul className="text-xs">
                            {s.validator_results.map((v) => (
                                <li key={v.id} className={v.passed ? "text-success-primary" : "text-error-primary"}>
                                    {v.passed ? "Passed" : "Failed"}: {v.detail}
                                </li>
                            ))}
                        </ul>
                    )}
                </li>
            ))}
        </ol>
    );
}
