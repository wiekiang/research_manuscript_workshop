import type { ScoreComponent } from "@/lib/api/types";
import { cx } from "@/utils/cx";

export const COMPONENT_LABEL: Record<string, string> = {
    topic_fit: "Topic fit",
    method_fit: "Method fit",
    venue_confidence: "Source confidence",
    time_to_complete: "Time to complete",
    deadline_slack: "Deadline slack",
    cost: "Cost",
};

/** Score in percent, or "unknown" when the component could not be estimated (never rendered as 0). */
export function formatComponentScore(score: number | null | undefined): string {
    if (score === null || score === undefined || Number.isNaN(score)) return "unknown";
    return `${Math.round(score * 100)}%`;
}

/**
 * Explainable relevance components for one candidate. Each shows its score (or "unknown"), the uncertainty of the
 * estimate and the evidence used. This is relevance to your profile, not a judgement of venue reputation.
 */
export function ScoreBreakdown({ components, total }: { components: ScoreComponent[]; total?: number }) {
    return (
        <div className="flex flex-col gap-2">
            {total !== undefined && (
                <p className="text-sm text-secondary">
                    <span className="font-semibold text-primary">Profile relevance {formatComponentScore(total)}</span>{" "}
                    <span className="text-tertiary">(weighted over the components that could be estimated; not a reputation score)</span>
                </p>
            )}
            <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label="Score components">
                {components.map((c) => {
                    const unknown = c.score === null || c.score === undefined;
                    return (
                        <div key={c.name} data-testid={`component-${c.name}`} className="flex flex-col gap-1 rounded-lg bg-secondary_subtle p-3 ring-1 ring-secondary">
                            <div className="flex items-center justify-between gap-2">
                                <dt className="text-xs font-semibold text-secondary">{COMPONENT_LABEL[c.name] ?? c.name}</dt>
                                <dd className={cx("text-sm font-semibold", unknown ? "text-tertiary italic" : "text-primary")}>{formatComponentScore(c.score)}</dd>
                            </div>
                            {!unknown && (
                                <div className="h-1.5 w-full overflow-hidden rounded-full bg-quaternary" aria-hidden="true">
                                    <div className="h-full rounded-full bg-fg-brand-primary" style={{ width: `${Math.round((c.score ?? 0) * 100)}%` }} />
                                </div>
                            )}
                            <dd className="text-xs text-tertiary">{c.uncertainty}</dd>
                            {c.evidence.length > 0 && (
                                <dd className="text-xs text-tertiary">
                                    {c.evidence.map((e) => (
                                        <span key={e} className="block">
                                            {e}
                                        </span>
                                    ))}
                                </dd>
                            )}
                        </div>
                    );
                })}
            </dl>
        </div>
    );
}
