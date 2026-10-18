import type { TemplateEntry } from "@/lib/api/types";

/** Plain-language meaning of a template's register status (always shown next to the badge). */
export const TEMPLATE_STATUS_TEXT: Record<string, string> = {
    analyzing: "Retrieval, safe archive analysis and sample compiles are running.",
    rejected: "The archive failed the safety checks and was not opened further.",
    unsupported: "No adapter can handle this template, so packages built from it are labelled not submission-ready.",
    validated: "Analysed safely and ready for sample compiles; confirm it once a clean compile exists.",
    confirmed: "You confirmed the official source and mode of this template.",
    failed: "The import task failed; see the activity log.",
};

export function templateLabel(t: Pick<TemplateEntry, "label" | "supported">): { text: string; tone: "ok" | "blocked" } {
    return t.label === "submission_ready_capable" && t.supported
        ? { text: "Can support a submission-ready package", tone: "ok" }
        : { text: "Not submission-ready", tone: "blocked" };
}

/** Why the Confirm action is unavailable, or null when it may be offered. */
export function confirmBlockReason(t: Pick<TemplateEntry, "supported" | "status" | "compile_runs">): string | null {
    if (t.status === "confirmed") return "Already confirmed.";
    if (!t.supported) return "Unsupported or rejected templates cannot be confirmed for submission.";
    if (t.status === "analyzing") return "Wait for analysis and the sample compiles to finish.";
    if (!t.compile_runs.some((r) => r.kind === "sample" && r.status === "compiled")) return "A clean sample compile is required first.";
    return null;
}
