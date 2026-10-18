import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IntegrityReport } from "@/components/integrity/integrity-report";
import { ApiError } from "@/lib/api/client";
import type { ClaimCheck, IntegrityReportEntry, ReviewFinding, ReviewReportSummary, ReviewRound } from "@/lib/api/types";
import { checkStatusKey, groupFindings, openBlocking, refusalHint, reportStatusKey, resolutionOptions } from "@/lib/review";
import { ClaimChecks } from "./claim-checks";
import { CompliancePanel } from "./compliance-panel";
import { FindingsPanel } from "./findings-panel";
import { MetaReviewPanel, ReportCards } from "./report-cards";

const finding = (over: Partial<ReviewFinding> = {}): ReviewFinding => ({
    id: "f1",
    function: "scientific",
    severity: "major",
    category: "conclusions",
    title: "The conclusion generalises from eight R pipelines",
    rationale: "Exploratory sample of eight.",
    check: "Compare the conclusion with the sample size.",
    proposed_fix: "Qualify the sentence.",
    span_ids: ["S-559ceb2c4a"],
    claim_ids: [],
    artifact_ids: [],
    rule_ids: [],
    status: "open",
    resolution_note: null,
    resolved_by: null,
    resolved_at: null,
    resolved_in_version: null,
    ...over,
});

const report = (over: Partial<ReviewReportSummary> = {}): ReviewReportSummary => ({
    function: "scientific",
    status: "performed",
    artifact_id: "a1",
    frozen_at: "2026-10-18T01:00:00Z",
    summary: {},
    provenance: {},
    ...over,
});

afterEach(() => vi.restoreAllMocks());

describe("not performed is never rendered as passed", () => {
    it("maps report and check statuses to distinct keys", () => {
        expect(reportStatusKey("not_performed")).toBe("not_performed");
        expect(reportStatusKey("partial")).toBe("report_partial");
        expect(reportStatusKey("performed")).toBe("report_performed");
        expect(checkStatusKey("not_performed")).toBe("not_performed");
        expect(checkStatusKey("something_new")).toBe("manual_check");
    });

    it("shows a not-performed report with its reason and no 'Passed' badge", () => {
        render(<ReportCards reports={[report({ status: "not_performed", summary: { reason: "not_performed: fixture_missing" } })]} functions={["scientific"]} />);
        const card = screen.getByTestId("review-report");
        expect(card.dataset.status).toBe("not_performed");
        expect(within(card).getByText("Not performed")).toBeInTheDocument();
        expect(within(card).queryByText("Passed")).toBeNull();
        expect(within(card).getByText(/fixture_missing/)).toBeInTheDocument();
    });

    it("labels a fixture-replayed scientific review as fixture output, never as human", () => {
        render(<ReportCards reports={[report({ summary: { conclusions: "One sentence generalises." }, provenance: { provider: "fixture", model: "fixture-recorded-1", label: "fixture output (test/demo only)" } })]} functions={["scientific"]} />);
        expect(screen.getByText(/Fixture output \(test\/demo only\)/)).toBeInTheDocument();
        expect(screen.getByText(/Model-assisted review · fixture/)).toBeInTheDocument();
        expect(screen.getByText("One sentence generalises.")).toBeInTheDocument();
        expect(screen.queryByText(/human/i)).toBeNull();
    });

    it("renders not-performed compliance checks as not performed", () => {
        const round: ReviewRound = {
            id: "r1", manuscript_version: 3, manuscript_version_id: "v3", status: "complete", functions: ["compliance"], task_id: "t",
            created_at: "2026-10-18T01:00:00Z", meta: null, meta_artifact_id: null,
            reports: [report({ function: "compliance", status: "partial", summary: { checks: [
                { id: "cfp.official_rules", status: "not_performed", detail: "no confirmed official CFP snapshot for the target venue/track", blocking: true, rule_id: null, quote: null, source: null },
                { id: "anonymization.visual_inspection", status: "manual_check", detail: "inspect figures by eye", blocking: true, rule_id: "r", quote: "double-blind", source: "https://example.org/cfp" },
            ] } })],
            compliance_decisions: [],
        };
        render(<CompliancePanel round={round} declaration="I reviewed this check." canEdit onChanged={() => {}} />);
        const [np, manual] = screen.getAllByTestId("compliance-check");
        expect(np.dataset.status).toBe("not_performed");
        expect(within(np).getByText("Not performed")).toBeInTheDocument();
        expect(within(np).queryByText("Passed")).toBeNull();
        expect(within(manual).getByRole("button", { name: "Record signed decision" })).toBeInTheDocument();
        expect(within(np).queryByRole("button")).toBeNull();
    });

    it("lists not-performed functions in the meta-review and states that review is diagnostic", () => {
        render(<MetaReviewPanel meta={{ counts: { technical: { blocker: 0, major: 0, minor: 0, suggestion: 0 } }, disagreements: [], not_performed: [{ function: "technical", detail: "no raw outputs" }], note: "AI review is diagnostic; it is not an acceptance decision." }} />);
        expect(screen.getByText("AI review is diagnostic; it is not an acceptance decision.")).toBeInTheDocument();
        expect(screen.getByTestId("meta-not-performed")).toHaveTextContent("Technical recomputation was not performed: no raw outputs.");
        expect(screen.queryByText(/score/i)).toBeNull();
    });

    it("shows source checks that did not run as not performed", () => {
        const checks: ClaimCheck[] = [{ claim_key: "CLM-0002", critical: true, selection: "critical", source_status: "not_performed", source_detail: "the stored source text is unavailable", meaning: [], method: "deterministic", reused: false }];
        render(<ClaimChecks checks={checks} samplingRule={{ id: "risk-sample-v1", description: "Every critical claim is checked." }} summary={{ unchecked_noncritical: ["CLM-0009"] }} />);
        expect(screen.getByText("Source: not performed")).toBeInTheDocument();
        expect(screen.getByTestId("unchecked-noncritical")).toHaveTextContent("CLM-0009");
        expect(screen.getByText(/risk-sample-v1/)).toBeInTheDocument();
    });
});

describe("findings grouping", () => {
    it("groups by function in fixed order, most severe first", () => {
        const g = groupFindings([
            finding({ id: "a", function: "citation_evidence", severity: "minor" }),
            finding({ id: "b", function: "citation_evidence", severity: "blocker" }),
            finding({ id: "c", function: "scientific", severity: "suggestion" }),
            finding({ id: "d", function: "compliance", severity: "blocker" }),
        ]);
        expect(g.map((x) => x.fn)).toEqual(["scientific", "citation_evidence", "compliance"]);
        expect(g[1].bySeverity.map((s) => s.severity)).toEqual(["blocker", "minor"]);
    });

    it("counts only open blocker/major findings of the scientific gate functions", () => {
        const fs = [finding(), finding({ id: "x", status: "accepted_risk" }), finding({ id: "y", function: "compliance", severity: "blocker" }), finding({ id: "z", severity: "minor" })];
        expect(openBlocking(fs).map((f) => f.id)).toEqual(["f1"]);
    });

    it("renders findings with links to the manuscript sentences and never offers accepted risk for a blocker", () => {
        render(<FindingsPanel projectId="p1" findings={[finding(), finding({ id: "b", severity: "blocker", function: "citation_evidence", category: "unsupported" })]} canEdit onChanged={() => {}} />);
        const groups = screen.getAllByTestId("finding-group");
        expect(groups.map((g) => g.dataset.function)).toEqual(["scientific", "citation_evidence"]);
        expect(screen.getAllByRole("link", { name: "S-559ceb2c4a" })[0]).toHaveAttribute("href", "/projects/p1/manuscript#span-S-559ceb2c4a");
        expect(resolutionOptions({ severity: "blocker" }).map((o) => o.value)).toEqual(["fixed", "rejected_with_reason"]);
        expect(resolutionOptions({ severity: "major" }).map((o) => o.value)).toContain("accepted_risk");
    });
});

describe("server refusals are shown verbatim", () => {
    it("shows the API message and code, plus guidance, when a resolution is refused", async () => {
        const { api } = await import("@/lib/api/client");
        vi.spyOn(api, "post").mockRejectedValue(new ApiError(409, "no_newer_version", "edit the manuscript first; the fix is checked by the next review round", null, "req-1"));
        render(<FindingsPanel projectId="p1" findings={[finding()]} canEdit onChanged={() => {}} />);
        fireEvent.click(screen.getByRole("button", { name: "Resolve finding" }));
        fireEvent.change(screen.getByRole("textbox", { name: /Note/ }), { target: { value: "reworded" } });
        fireEvent.click(screen.getByRole("button", { name: "Record resolution" }));
        expect(await screen.findByText("edit the manuscript first; the fix is checked by the next review round")).toBeInTheDocument();
        expect(screen.getByText(/Error code no_newer_version/)).toBeInTheDocument();
        expect(screen.getByTestId("refusal-hint")).toHaveTextContent("“fixed” is confirmed by the next review round");
    });

    it("has guidance for every documented refusal code", () => {
        for (const code of ["no_newer_version", "blocker_cannot_be_accepted", "must_fix", "rationale_required", "revision_limit_reached", "declaration_mismatch", "not_decidable"]) {
            expect(refusalHint(new ApiError(409, code, "m", null, null))).toBeTruthy();
        }
        expect(refusalHint(new Error("x"))).toBeNull();
    });
});

describe("integrity report", () => {
    const rep: IntegrityReportEntry = {
        id: "i1", status: "complete", manuscript_version: 5, engine: "rp-integrity/1", artifact_id: null, created_at: "2026-10-18T01:00:00Z",
        checks: [
            { id: "references.identity", title: "Fabricated or mismatched references", status: "failed", detail: "unverified identity: ['fake']", evidence: {}, scope: "bibliography", limitations: null, blocking: true, requires_decision: false, decision: null },
            { id: "text.overlap", title: "Duplicate or preexisting text", status: "warning", detail: "1 span(s) largely reuse wording", evidence: {}, scope: "spans", limitations: "Compared only against 1 source text(s) stored in this project; this is not comprehensive plagiarism detection.", blocking: true, requires_decision: true, decision: null },
            { id: "declarations", title: "Disclosures", status: "not_performed", detail: "author disclosures have not been recorded yet", evidence: {}, scope: "author records", limitations: null, blocking: true, requires_decision: false, decision: null },
        ],
        summary: { failed: ["references.identity", "declarations"], awaiting_decision: ["text.overlap"], passed: false, engine: "rp-integrity/1", disclaimer: "This report lists the checks performed, their scope and limitations. It does not certify research integrity, and the text-overlap check is not comprehensive plagiarism detection." },
    };

    it("shows the disclaimer verbatim, offers decisions only for warnings/manual checks and never shows not performed as passed", () => {
        render(<IntegrityReport report={rep} declaration="I reviewed this check." canEdit onChanged={() => {}} />);
        expect(screen.getByTestId("integrity-disclaimer")).toHaveTextContent(rep.summary.disclaimer);
        const [failed, warning, np] = screen.getAllByTestId("integrity-check");
        expect(within(failed).queryByRole("button")).toBeNull();
        expect(within(warning).getByRole("button", { name: "Record signed decision" })).toBeInTheDocument();
        expect(within(np).getByText("Not performed")).toBeInTheDocument();
        expect(within(np).queryByText("Passed")).toBeNull();
        expect(screen.getByText(/not comprehensive plagiarism detection\.$/, { selector: "p.text-xs" })).toBeInTheDocument();
    });
});

describe("task cancel and retry", () => {
    const task = (state: string) => ({ id: "t1", kind: "review_run", state, attempt: 1, max_attempts: 3, owner: "platform", error_code: null, error_message: null, waiting_reason: null, progress: {}, result: {}, output_artifact_ids: [], created_at: "", updated_at: "", started_at: null, finished_at: null, estimated_cost_cents: 120, params: {} });

    it("offers cancel for running tasks and nothing for succeeded ones", async () => {
        const { TaskActions } = await import("@/components/research/task-actions");
        const { rerender } = render(<TaskActions projectId="p" task={task("running")} />);
        expect(screen.getByRole("button", { name: "Cancel task" })).toBeInTheDocument();
        rerender(<TaskActions projectId="p" task={task("succeeded")} />);
        expect(screen.queryByTestId("task-actions")).toBeNull();
    });

    it("asks for cost confirmation when the server requires it before retrying", async () => {
        const { TaskActions } = await import("@/components/research/task-actions");
        const { api } = await import("@/lib/api/client");
        const post = vi.spyOn(api, "post").mockRejectedValueOnce(new ApiError(422, "cost_confirmation_required", "this task can incur model or compute cost; confirm to retry", null, null)).mockResolvedValueOnce({});
        render(<TaskActions projectId="p" task={task("failed_terminal")} />);
        fireEvent.click(screen.getByRole("button", { name: "Retry from recorded inputs" }));
        expect(await screen.findByText("this task can incur model or compute cost; confirm to retry")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("checkbox", { name: /I accept that retrying can incur model or compute cost/ }));
        fireEvent.click(screen.getByRole("button", { name: "Retry from recorded inputs" }));
        await vi.waitFor(() => expect(post).toHaveBeenLastCalledWith("/v1/projects/p/tasks/t1/retry", { confirm_cost: true }));
    });
});
