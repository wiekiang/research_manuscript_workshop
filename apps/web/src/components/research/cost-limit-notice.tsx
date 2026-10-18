import type { BudgetStatus } from "@/lib/api/types";
import { formatMoney } from "@/lib/format";
import { cx } from "@/utils/cx";

export function BudgetBar({ budget, className }: { budget: BudgetStatus; className?: string }) {
    const used = Math.min(100, budget.percent_used);
    const tone = used >= 100 ? "bg-error-solid" : used >= 80 ? "bg-warning-solid" : "bg-brand-solid";
    return (
        <div className={cx("flex flex-col gap-1.5", className)}>
            <div className="flex justify-between text-sm">
                <span className="text-secondary">
                    {formatMoney(budget.spent_cents + budget.reserved_cents, budget.currency)} used or reserved of {formatMoney(budget.cap_cents, budget.currency)}
                </span>
                <span className="font-medium text-primary">{budget.percent_used}%</span>
            </div>
            <div
                className="h-2 w-full overflow-hidden rounded-full bg-quaternary"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={used}
                aria-label="Budget used"
            >
                <div className={cx("h-full rounded-full", tone)} style={{ width: `${used}%` }} />
            </div>
            <p className="text-xs text-tertiary">Remaining {formatMoney(Math.max(0, budget.remaining_cents), budget.currency)}. Alerts at 50%, 80% and 100%; paid work stops at the cap.</p>
        </div>
    );
}

export function CostLimitNotice({ budget }: { budget: BudgetStatus | undefined }) {
    if (!budget || budget.percent_used < 80) return null;
    const atCap = budget.percent_used >= 100 || budget.remaining_cents <= 0;
    return (
        <div role="status" className={cx("rounded-xl p-4 text-sm", atCap ? "bg-error-primary text-error-primary" : "bg-warning-primary text-utility-amber-700")}>
            {atCap
                ? "The project has reached its cost cap. New paid tasks are refused until a project owner raises the cap with a recorded rationale."
                : `The project has used ${budget.percent_used}% of its cost cap. Review spending before starting large tasks.`}
        </div>
    );
}
