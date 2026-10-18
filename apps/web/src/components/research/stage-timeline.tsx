import { Check, PenTool02 } from "@untitledui/icons";
import type { ProjectState } from "@/lib/api/types";
import { HUMAN_GATE_STATES, MAIN_SEQUENCE, OVERLAYS, STATE_LABEL, stateIndex } from "@/lib/states";
import { cx } from "@/utils/cx";

interface StageTimelineProps {
    state: ProjectState;
    resumeState?: ProjectState | null;
    overlayReason?: string | null;
    compact?: boolean;
    className?: string;
}

/**
 * The canonical lifecycle as a gated ledger. Human gates (CFP, H1–H4) carry an amber signature mark so the places
 * where a researcher must sign are visible at a glance; the current stage is named in text, never only by color.
 */
export function StageTimeline({ state, resumeState, overlayReason, compact = false, className }: StageTimelineProps) {
    const overlay = OVERLAYS.includes(state) ? state : null;
    const effective = overlay ? (resumeState ?? "CREATED") : state;
    const current = stateIndex(effective);

    if (compact) {
        return (
            <div className={cx("flex flex-col gap-1.5", className)}>
                <div className="flex gap-0.5" aria-hidden="true">
                    {MAIN_SEQUENCE.map((s, i) => (
                        <span
                            key={s}
                            className={cx(
                                "h-1.5 flex-1 rounded-full",
                                i < current && "bg-brand-solid",
                                i === current && (overlay ? "bg-fg-quaternary" : HUMAN_GATE_STATES[s] ? "bg-warning-solid" : "bg-brand-solid"),
                                i > current && "bg-quaternary",
                            )}
                        />
                    ))}
                </div>
                <p className="text-xs text-tertiary">
                    <span className="font-medium text-secondary">{STATE_LABEL[effective]}</span>
                    {overlay && <span> · {STATE_LABEL[overlay]}</span>}
                    <span className="sr-only">
                        {" "}
                        stage {current + 1} of {MAIN_SEQUENCE.length}
                    </span>
                </p>
            </div>
        );
    }

    return (
        <nav aria-label="Project lifecycle" className={className}>
            {overlay && (
                <p className="mb-3 rounded-lg bg-secondary px-3 py-2 text-sm text-secondary">
                    <span className="font-semibold">{STATE_LABEL[overlay]}.</span>{" "}
                    {overlay === "CANCELLED" ? "No further work will run; the audit history is kept." : `Work resumes at ${STATE_LABEL[effective]}.`}
                    {overlayReason && <span className="text-tertiary"> Reason: {overlayReason}</span>}
                </p>
            )}
            <ol className="grid grid-cols-1 gap-y-0 sm:grid-cols-2 lg:grid-cols-1">
                {MAIN_SEQUENCE.map((s, i) => {
                    const done = i < current;
                    const isCurrent = i === current;
                    const gate = HUMAN_GATE_STATES[s];
                    return (
                        <li key={s} aria-current={isCurrent ? "step" : undefined} className="relative flex items-center gap-3 py-1.5">
                            <span
                                className={cx(
                                    "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ring-1",
                                    done && "bg-brand-solid text-white ring-transparent",
                                    isCurrent && !gate && "bg-brand-primary text-brand-secondary ring-brand",
                                    isCurrent && gate && "bg-warning-primary text-utility-amber-700 ring-utility-amber-400",
                                    !done && !isCurrent && "bg-primary text-quaternary ring-secondary",
                                )}
                            >
                                {done ? <Check className="size-3.5" aria-hidden="true" /> : i + 1}
                            </span>
                            <span className={cx("text-sm", isCurrent ? "font-semibold text-primary" : done ? "text-secondary" : "text-tertiary")}>
                                {STATE_LABEL[s]}
                                {isCurrent && <span className="sr-only"> (current stage)</span>}
                                {done && <span className="sr-only"> (passed)</span>}
                            </span>
                            {gate && (
                                <span
                                    className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-utility-amber-700"
                                    title={`Human signature required: ${gate}`}
                                >
                                    <PenTool02 className="size-3.5" aria-hidden="true" />
                                    {gate}
                                    <span className="sr-only"> human gate</span>
                                </span>
                            )}
                        </li>
                    );
                })}
            </ol>
        </nav>
    );
}
