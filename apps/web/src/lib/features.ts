/**
 * Single source for which workspaces exist in this release and how they run (spec §0: the dashboard must show which
 * stages are automated, manual, or unavailable). Used by navigation, project tabs and the dashboard.
 */
import type { FC } from "react";
import {
    Activity,
    BarChart03,
    BookOpen01,
    CheckDone01,
    ClipboardCheck,
    CoinsStacked01,
    Database01,
    Dataflow03,
    File06,
    FileCheck02,
    Beaker02,
    LayoutAlt01,
    MessageTextSquare01,
    Lightbulb02,
    SearchRefraction,
    Settings01,
    ShieldTick,
    Signal01,
    Users01,
} from "@untitledui/icons";

export type Availability = "automated" | "manual" | "assisted" | "unavailable";

export interface Workspace {
    key: string;
    label: string;
    /** Path segment under /projects/[id]; empty string = overview. */
    segment: string;
    icon: FC<{ className?: string }>;
    availability: Availability;
    milestone: string;
    /** What happens in this release, in plain language. */
    summary: string;
    /** Shown in project navigation only when the selected study type is one of these (method-specific workspaces). */
    studyTypes?: string[];
}

export const PROJECT_WORKSPACES: Workspace[] = [
    { key: "overview", label: "Overview", segment: "", icon: LayoutAlt01, availability: "manual", milestone: "M0", summary: "Stage timeline, next human action, approvals and budget." },
    { key: "cfp", label: "Call for papers", segment: "cfp", icon: File06, availability: "assisted", milestone: "M1", summary: "Official CFP import, rule extraction with independent checks, and your resolution of ambiguous rules." },
    { key: "discovery", label: "Conference discovery", segment: "discovery", icon: Signal01, availability: "assisted", milestone: "M2", summary: "Ranking of verified official sources against your research profile, with component scores and their uncertainty." },
    { key: "templates", label: "LaTeX template", segment: "templates", icon: FileCheck02, availability: "assisted", milestone: "M3", summary: "Official template retrieval, safe analysis, sandboxed sample compilation and your confirmation of the template mode." },
    { key: "literature", label: "Literature", segment: "literature", icon: BookOpen01, availability: "assisted", milestone: "M4", summary: "Scholarly search of enabled sources, DOI identity checks, rights-aware full text and a coverage report that states its limits." },
    { key: "evidence", label: "Evidence & claims", segment: "evidence", icon: Database01, availability: "assisted", milestone: "M4", summary: "Verbatim evidence passages, the claim registry and policy-based verification with method labels." },
    { key: "opportunities", label: "Research direction", segment: "direction", icon: Lightbulb02, availability: "assisted", milestone: "M4 / M5", summary: "Advisory gap proposals, feasibility, the editable Paper Rationale, study type selection and your H1 decision." },
    { key: "methodology", label: "Methodology & protocol", segment: "methodology", icon: ClipboardCheck, availability: "assisted", milestone: "M5", summary: "Method workflow, versioned protocol, model-assisted independent review (or a recorded waiver) and your H2 freeze." },
    { key: "contributions", label: "Contributions", segment: "contributions", icon: Users01, availability: "manual", milestone: "M5", summary: "Your data, code and results with deterministic assurance levels, method stages, the contribution matrix, gap assessment, H3 and the contribution ledger." },
    { key: "review-workspace", label: "Review workspace", segment: "review-workspace", icon: Dataflow03, availability: "assisted", milestone: "M10", studyTypes: ["systematic_review", "meta_analysis", "mapping_review", "scoping_review", "tertiary_review"], summary: "Searches run exactly as frozen in the protocol, human screening with the protocol's exclusion reasons, passage-linked extraction and appraisal, a platform-computed synthesis (pooling, charting map or review overlap) and a reproducibility appendix." },
    { key: "qualitative", label: "Qualitative analysis", segment: "qualitative", icon: MessageTextSquare01, availability: "manual", milestone: "M10", studyTypes: ["empirical_qualitative"], summary: "Codebook, coded segments checked verbatim against their sources, themes traced to coded segments and your interpretation." },
    { key: "experiments", label: "Experiments", segment: "experiments", icon: Beaker02, availability: "assisted", milestone: "M9", summary: "Owner-approved plans run under the frozen protocol in a no-network sandbox with pinned image, hashes and seed; a separate validator recomputes metrics from raw outputs, reruns check reproduction, and failed runs never become results." },
    { key: "manuscript", label: "Manuscript", segment: "manuscript", icon: BarChart03, availability: "assisted", milestone: "M6", summary: "Evidence-grounded drafting with sentence-level provenance, deterministic span checks, versioned edits, explicit merge of generated drafts and sandboxed compilation." },
    { key: "review", label: "Independent review", segment: "review", icon: SearchRefraction, availability: "assisted", milestone: "M7", summary: "Separately frozen scientific, citation/evidence, technical and venue-compliance reviews, a meta-review, your resolution of findings and at most two automatic revision cycles." },
    { key: "integrity", label: "Research integrity", segment: "integrity", icon: ShieldTick, availability: "automated", milestone: "M7", summary: "Deterministic cross-stage integrity checks with stated scope and limits; failed checks block and uncertainty needs your signed decision." },
    { key: "submission", label: "Submission package", segment: "submission", icon: CheckDone01, availability: "assisted", milestone: "M8", summary: "Authors and their assent, disclosures with the venue AI policy, deadline eligibility for the intended action, the readiness assessment, H4 sign-off of a frozen content manifest and a verified package for your own export. The platform never submits for you." },
    { key: "activity", label: "Activity & audit", segment: "activity", icon: Activity, availability: "automated", milestone: "M0", summary: "Agent tasks, workflow states and the append-only event history." },
    { key: "costs", label: "Costs", segment: "costs", icon: CoinsStacked01, availability: "automated", milestone: "M0", summary: "Budget cap, alerts, model calls and data-flow permissions." },
    { key: "settings", label: "Project settings", segment: "settings", icon: Settings01, availability: "manual", milestone: "M0", summary: "Members, roles, corresponding author and approval history." },
];

export const GLOBAL_WORKSPACES: Workspace[] = [
    { key: "registry", label: "Official-source registry", segment: "conferences/registry", icon: Signal01, availability: "manual", milestone: "M2", summary: "Curated official organizer sources that discovery may fetch; curated by platform operators." },
];

export const AVAILABILITY_LABEL: Record<Availability, string> = {
    automated: "Automated",
    assisted: "Automated with your review",
    manual: "You do this",
    unavailable: "Not available in this release",
};

/** Workspaces for project navigation: method-specific ones appear only for their study types. */
export function workspacesFor(studyType: string | null | undefined): Workspace[] {
    return PROJECT_WORKSPACES.filter((w) => !w.studyTypes || (!!studyType && w.studyTypes.includes(studyType)));
}

export function workspaceBySegment(segment: string): Workspace | undefined {
    return PROJECT_WORKSPACES.find((w) => w.segment === segment);
}
