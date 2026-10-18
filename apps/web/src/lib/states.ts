import type { ProjectState } from "./api/types";
import machine from "./state_machine.json";

export const MAIN_SEQUENCE: ProjectState[] = [
    "CREATED",
    "TARGET_REVIEW",
    "DIRECTION_REVIEW",
    "PROTOCOL_REVIEW",
    "RESEARCH_ACTIVE",
    "OUTCOME_REVIEW",
    "DRAFTING",
    "SCIENTIFIC_REVIEW",
    "COMPLIANCE_REVIEW",
    "FINAL_APPROVAL",
    "APPROVED_FOR_EXPORT",
    "PACKAGE_READY",
];

export const OVERLAYS: ProjectState[] = ["PAUSED", "BLOCKED", "CANCELLED"];

export const STATE_LABEL: Record<ProjectState, string> = {
    CREATED: "Created",
    TARGET_REVIEW: "Target review",
    DIRECTION_REVIEW: "Direction review (H1)",
    PROTOCOL_REVIEW: "Protocol review (H2)",
    RESEARCH_ACTIVE: "Research active",
    OUTCOME_REVIEW: "Outcome review (H3)",
    DRAFTING: "Drafting",
    SCIENTIFIC_REVIEW: "Scientific review",
    COMPLIANCE_REVIEW: "Compliance review",
    FINAL_APPROVAL: "Final approval (H4)",
    APPROVED_FOR_EXPORT: "Approved for export",
    PACKAGE_READY: "Package ready",
    PAUSED: "Paused",
    BLOCKED: "Blocked",
    CANCELLED: "Cancelled",
};

/** States that wait on a human signature before the project can move on. */
export const HUMAN_GATE_STATES: Partial<Record<ProjectState, string>> = {
    TARGET_REVIEW: "CFP",
    DIRECTION_REVIEW: "H1",
    PROTOCOL_REVIEW: "H2",
    OUTCOME_REVIEW: "H3",
    FINAL_APPROVAL: "H4",
};

export function transitionDescription(from: string): string | undefined {
    return (machine.transitions as { from: string; description: string }[]).find((t) => t.from === from)?.description;
}

export function stateIndex(s: ProjectState): number {
    return MAIN_SEQUENCE.indexOf(s);
}
