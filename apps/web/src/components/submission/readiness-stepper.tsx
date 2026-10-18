import { CheckCircle } from "@untitledui/icons";
import { STAGES, STAGE_LABEL, stageIndex } from "@/lib/submission";
import { cx } from "@/utils/cx";

/** The exact §2.15 label sequence. A stage counts as reached only when the server's evidence says so. */
export function ReadinessStepper({ stage }: { stage: string }) {
    const at = stageIndex(stage);
    return (
        <ol aria-label="Submission readiness stages" className="flex flex-col gap-2 sm:flex-row sm:flex-wrap" data-testid="readiness-stepper">
            {STAGES.map((s, i) => {
                const reached = i <= at;
                const current = i === at;
                return (
                    <li
                        key={s}
                        data-stage={s}
                        data-reached={reached}
                        aria-current={current ? "step" : undefined}
                        className={cx(
                            "flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
                            current ? "border-brand bg-brand-primary_alt font-semibold text-brand-secondary" : reached ? "border-secondary text-secondary" : "border-secondary text-quaternary",
                        )}
                    >
                        <span className="font-mono text-xs">{i + 1}</span>
                        {reached && <CheckCircle className="size-4 text-fg-success-primary" aria-hidden="true" />}
                        <span>{STAGE_LABEL[s]}</span>
                        {current && <span className="sr-only">(current stage)</span>}
                    </li>
                );
            })}
        </ol>
    );
}
