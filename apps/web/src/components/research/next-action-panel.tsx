import { ArrowRight, CheckCircle, PenTool02, XCircle } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import type { NextStep, ProjectState } from "@/lib/api/types";
import { HUMAN_GATE_STATES, STATE_LABEL } from "@/lib/states";
import { cx } from "@/utils/cx";

/** Where each gate is resolved in the app (direct action links). */
const GATE_ACTIONS: Record<string, { label: string; segment: string }> = {
    "target.selected": { label: "Import the CFP and choose a track", segment: "cfp" },
    "cfp.confirmed": { label: "Resolve and confirm CFP rules", segment: "cfp" },
    "h1.approved": { label: "Review the research direction (H1)", segment: "direction" },
    "h2.approved": { label: "Freeze the protocol (H2)", segment: "methodology" },
    "method.required_stages_complete": { label: "Complete the method stages", segment: "contributions" },
    "h3.approved": { label: "Validate outcomes (H3)", segment: "contributions/outcomes" },
    "manuscript.complete": { label: "Finish the manuscript", segment: "manuscript" },
    "review.passed": { label: "Resolve review findings", segment: "review" },
    "compliance.checked": { label: "Run compliance checks", segment: "review" },
    "integrity.checked": { label: "Run integrity checks", segment: "review" },
    "readiness.pre_approval": { label: "Record the readiness assessment", segment: "submission" },
    "h4.approved": { label: "Final approval (H4)", segment: "submission" },
    "package.verified": { label: "Build and verify the package", segment: "submission" },
};

interface Props {
    projectId: string;
    state: ProjectState;
    nextStep: NextStep | null | undefined;
    className?: string;
}

export function NextActionPanel({ projectId, state, nextStep, className }: Props) {
    const gate = HUMAN_GATE_STATES[state];
    const failing = nextStep?.gates.filter((g) => !g.passed) ?? [];
    return (
        <section
            aria-labelledby="next-action-title"
            className={cx(
                "flex flex-col gap-4 rounded-2xl border p-5",
                gate && failing.length ? "border-utility-amber-300 bg-warning-primary" : "border-secondary bg-primary",
                className,
            )}
        >
            <div className="flex items-start gap-3">
                {gate ? (
                    <PenTool02 className="mt-1 size-5 shrink-0 text-fg-warning-primary" aria-hidden="true" />
                ) : (
                    <ArrowRight className="mt-1 size-5 shrink-0 text-fg-brand-primary" aria-hidden="true" />
                )}
                <div className="flex flex-col gap-1">
                    <h2 id="next-action-title" className="font-display text-lg font-semibold text-primary">
                        What is needed next
                    </h2>
                    {nextStep?.overlay ? (
                        <p className="text-sm text-secondary">{nextStep.message}</p>
                    ) : nextStep?.target_state ? (
                        <p className="text-sm text-secondary">
                            To move to <span className="font-semibold">{STATE_LABEL[nextStep.target_state as ProjectState] ?? nextStep.target_state}</span>
                            {nextStep.description ? `: ${nextStep.description.charAt(0).toLowerCase()}${nextStep.description.slice(1)}.` : "."}
                        </p>
                    ) : (
                        <p className="text-sm text-secondary">The project has reached the end of the lifecycle available in this release.</p>
                    )}
                </div>
            </div>
            {nextStep && nextStep.gates.length > 0 && (
                <ul className="flex flex-col gap-3" aria-label="Gate checks">
                    {nextStep.gates.map((g) => {
                        const action = GATE_ACTIONS[g.gate_id];
                        return (
                            <li key={g.gate_id} className="flex flex-col gap-1.5 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                                <div className="flex items-center gap-2">
                                    {g.passed ? (
                                        <CheckCircle className="size-4 text-fg-success-primary" aria-hidden="true" />
                                    ) : (
                                        <XCircle className="size-4 text-fg-error-primary" aria-hidden="true" />
                                    )}
                                    <span className="text-sm font-medium text-primary">{action?.label ?? g.gate_id}</span>
                                    <span className="text-xs text-tertiary">{g.passed ? "Passed" : "Not yet satisfied"}</span>
                                </div>
                                {!g.passed && g.reasons.length > 0 && (
                                    <ul className="list-disc pl-10 text-sm text-secondary">
                                        {g.reasons.map((r) => (
                                            <li key={r}>{r}</li>
                                        ))}
                                    </ul>
                                )}
                                {!g.passed && action && (
                                    <div className="pl-6">
                                        <Button size="sm" color="link-color" href={`/projects/${projectId}/${action.segment}`}>
                                            {action.label}
                                        </Button>
                                    </div>
                                )}
                            </li>
                        );
                    })}
                </ul>
            )}
            {failing.length === 0 && nextStep?.ready && <p className="text-sm text-success-primary">Every gate for the next stage is satisfied.</p>}
        </section>
    );
}
