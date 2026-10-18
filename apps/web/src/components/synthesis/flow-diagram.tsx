import type { ReviewFlow } from "@/lib/api/types";
import { flowReconciles, flowRows } from "@/lib/synthesis";

function Box({ label, value, testId, tone = "default" }: { label: string; value: number; testId: string; tone?: "default" | "muted" | "end" }) {
    return (
        <div
            data-testid={testId}
            className={
                tone === "end"
                    ? "flex flex-col gap-0.5 rounded-lg bg-brand-primary_alt p-3 ring-1 ring-brand"
                    : tone === "muted"
                      ? "flex flex-col gap-0.5 rounded-lg bg-secondary p-3 ring-1 ring-secondary"
                      : "flex flex-col gap-0.5 rounded-lg bg-primary p-3 ring-1 ring-secondary"
            }
        >
            <span className="text-xs text-tertiary">{label}</span>
            <span className="text-lg font-semibold text-primary tabular-nums">{value}</span>
        </div>
    );
}

/**
 * PRISMA-style flow from the server's record counts. Nothing is recomputed here; a mismatch between boxes is flagged
 * (the stage validator would also refuse it).
 */
export function FlowDiagram({ flow }: { flow: ReviewFlow }) {
    const rows = Object.fromEntries(flowRows(flow).map((r) => [r.key, r]));
    const reasons = Object.entries(flow.excluded_full_text_reasons);
    const ok = flowReconciles(flow);
    return (
        <figure aria-label="Study flow" className="flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-2">
                <Box testId="flow-identified" label={rows.identified.label} value={flow.identified} />
                <Box testId="flow-duplicates" label={rows.duplicates_removed.label} value={flow.duplicates_removed} tone="muted" />
                <Box testId="flow-screened" label={rows.screened.label} value={flow.screened} />
                <Box testId="flow-screened-out" label={rows.screened_out.label} value={flow.screened_out} tone="muted" />
                <Box testId="flow-full-text" label={rows.full_text_assessed.label} value={flow.full_text_assessed} />
                <div className="flex flex-col gap-1 rounded-lg bg-secondary p-3 ring-1 ring-secondary" data-testid="flow-excluded-full-text">
                    <span className="text-xs text-tertiary">{rows.excluded_full_text.label}</span>
                    <span className="text-lg font-semibold text-primary tabular-nums">{flow.excluded_full_text}</span>
                    {reasons.length > 0 && (
                        <ul className="text-xs text-secondary">
                            {reasons.map(([r, n]) => (
                                <li key={r}>
                                    {r}: {n}
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
                <Box testId="flow-included" label={rows.included.label} value={flow.included} tone="end" />
                <div className="flex flex-col gap-1 rounded-lg p-3 text-xs text-tertiary ring-1 ring-secondary" data-testid="flow-awaiting">
                    <span>
                        {rows.awaiting_screening.label}: <span className="font-semibold text-primary">{flow.awaiting_screening}</span>
                    </span>
                    <span>
                        {rows.awaiting_full_text.label}: <span className="font-semibold text-primary">{flow.awaiting_full_text}</span>
                    </span>
                </div>
            </div>
            <figcaption className={ok ? "text-xs text-tertiary" : "text-xs text-error-primary"} data-testid="flow-reconciles" data-ok={ok}>
                {ok
                    ? "Counts derive from the stored search and screening records and reconcile."
                    : "These counts do not reconcile; the screening stage cannot validate until every record has a decision."}
            </figcaption>
        </figure>
    );
}
