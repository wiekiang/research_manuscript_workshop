import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api/client";
import type { AuthorsView, ContentManifestView, EligibilityResult, ExportPackageEntry, ReadinessView } from "@/lib/api/types";
import { disclosureProblems, emptyDisclosures, moveItem, packageLabel, serverProblems } from "@/lib/submission";
import { AuthorsEditor } from "./authors-editor";
import { FinalApprovalForm } from "./content-manifest";
import { EligibilityResultView } from "./eligibility-panel";
import { PackageCard } from "./packages-list";
import { ReadinessPanel } from "./readiness-panel";

afterEach(() => vi.restoreAllMocks());

const pkg = (over: Partial<ExportPackageEntry> = {}): ExportPackageEntry => ({
    id: "p1",
    status: "built",
    approved: false,
    label: "unapproved",
    artifact_id: "a1",
    checksum: "c".repeat(64),
    content_manifest_hash: null,
    problems: [],
    verified_at: null,
    created_at: "2026-10-18T01:00:00Z",
    name: "package-v5-UNAPPROVED-1.zip",
    stale: null,
    files: [{ path: "paper.pdf", sha256: "d".repeat(64) }],
    ...over,
});

const readiness = (over: Partial<ReadinessView> = {}): ReadinessView => ({
    current_stage: "research_proposal",
    gates: { "manuscript.complete": { gate_id: "manuscript.complete", passed: false, reasons: ["no manuscript"], evidence: {}, next_action: null } },
    items: [],
    notice: "The platform does not submit to any venue. PACKAGE_READY means ready for human export.",
    ...over,
});

const eligibility = (over: Partial<EligibilityResult> = {}): EligibilityResult => ({
    action: "camera_ready",
    status: "eligible",
    evaluated_at: "2027-02-01T00:00:00Z",
    governing: [{ id: "g1", kind: "camera_ready", due_at: "2027-04-16T06:59:00Z", timezone: "PDT", mandatory: true }],
    context: [{ id: "c1", kind: "full_paper", due_at: "2027-01-22T11:59:00Z", timezone: "AoE", mandatory: true, note: "passed, but it does not govern this action" }],
    pending_prerequisites: [],
    reasons: [],
    evaluator: "rp-deadline-evaluator/1",
    ...over,
});

describe("export packages", () => {
    it("labels an unapproved package prominently and an approved one as H4", () => {
        const { rerender } = render(<PackageCard p={pkg()} />);
        expect(screen.getByText("UNAPPROVED – for author review only")).toBeTruthy();
        expect(screen.getByText("none (not signed at H4)")).toBeTruthy();
        rerender(<PackageCard p={pkg({ approved: true, label: "approved", status: "verified", content_manifest_hash: "e".repeat(64) })} />);
        expect(screen.getByText("Approved (H4)")).toBeTruthy();
        expect(screen.getByText("Verified against the signed content manifest")).toBeTruthy();
        expect(packageLabel({ approved: false })).toMatch(/^UNAPPROVED/);
    });

    it("keeps a stale package visible with its reason", () => {
        render(<PackageCard p={pkg({ approved: true, stale: "H4 is invalidated: disclosures changed" })} />);
        expect(screen.getByTestId("package-stale").textContent).toContain("H4 is invalidated: disclosures changed");
    });
});

describe("no submit action anywhere", () => {
    it("never offers a submit button in packages, H4, eligibility or readiness", () => {
        const manifest: ContentManifestView = { items: [], problems: [], manuscript_version: 5, authors_without_approval: [], declaration: "I accept responsibility." };
        render(
            <div>
                <PackageCard p={pkg({ approved: true, status: "verified" })} />
                <FinalApprovalForm view={manifest} projectId="p" inFinalApproval onSigned={() => {}} />
                <EligibilityResultView result={eligibility()} />
                <ReadinessPanel view={readiness({ current_stage: "submission_ready_package" })} projectId="p" canEdit onChanged={() => {}} />
            </div>,
        );
        const names = screen.getAllByRole("button").map((b) => b.textContent ?? "");
        expect(names.some((n) => /\bsubmit\b/i.test(n))).toBe(false);
        expect(screen.getByTestId("readiness-notice").textContent).toBe("The platform does not submit to any venue. PACKAGE_READY means ready for human export.");
    });
});

describe("eligibility", () => {
    it("renders governing deadlines separately from unrelated passed deadlines", () => {
        render(<EligibilityResultView result={eligibility()} />);
        const governing = screen.getByTestId("eligibility-governing");
        const context = screen.getByTestId("eligibility-context");
        expect(within(governing).getByText("Camera ready")).toBeTruthy();
        expect(within(governing).queryByText("Full paper")).toBeNull();
        expect(within(context).getByText("Full paper")).toBeTruthy();
        expect(screen.getByTestId("eligibility-result").getAttribute("data-status")).toBe("eligible");
    });

    it("shows server reasons verbatim and never calls an unresolved deadline ineligible", () => {
        const reason = "no recorded deadline governs 'new_submission'; confirm the submission path from the official source";
        render(<EligibilityResultView result={eligibility({ action: "new_submission", status: "needs_human_resolution", governing: [], context: [], reasons: [reason] })} />);
        expect(screen.getByTestId("eligibility-reasons").textContent).toBe(reason);
        expect(screen.getByText("Needs your resolution")).toBeTruthy();
        expect(screen.queryByText("Not eligible for this action")).toBeNull();
    });
});

describe("authors", () => {
    const view: AuthorsView = {
        record_version: 0,
        authors: [],
        manuscript_version: null,
        author_approval_text: "approve",
        offline_attestation_text: "attest",
        note: "The contribution log is evidence for author review, never an authorship certification.",
    };

    it("shows the server's AI-author refusal verbatim", async () => {
        const problem = "author 1 (ChatGPT): AI tools cannot be listed as authors; describe AI use in the disclosure";
        const put = vi.spyOn(api, "put").mockRejectedValue(new ApiError(422, "invalid_authors", "the author record is incomplete", { problems: [problem] }, "req-1"));
        render(<AuthorsEditor view={view} members={[]} projectId="p1" canSave onSaved={() => {}} />);
        fireEvent.change(screen.getByLabelText(/Full name \(author 1\)/), { target: { value: "ChatGPT" } });
        fireEvent.click(screen.getByRole("button", { name: "Save author record" }));
        await waitFor(() => expect(screen.getByTestId("author-problems")).toBeTruthy());
        expect(screen.getByTestId("author-problems").textContent).toContain(problem);
        expect(put).toHaveBeenCalledWith("/v1/projects/p1/authors", expect.objectContaining({ expected_record_version: 0 }));
        const body = put.mock.calls[0][1] as { authors: { name: string; corresponding: boolean }[] };
        expect(body.authors[0]).toMatchObject({ name: "ChatGPT", corresponding: true });
    });

    it("reorders authors and reads problems only from the refusal details", () => {
        expect(moveItem(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
        expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
        expect(serverProblems({ problems: ["x"] })).toEqual(["x"]);
        expect(serverProblems({ reasons: ["x"] })).toEqual([]);
    });
});

describe("disclosures and readiness", () => {
    it("mirrors the server's minimum lengths", () => {
        const p = disclosureProblems(emptyDisclosures());
        expect(p).toHaveLength(7);
        expect(p[0]).toBe("Competing interests: at least 2 characters");
    });

    it("marks the live stage in the seven-stage sequence and keeps manual checks visible", () => {
        render(
            <ReadinessPanel
                view={readiness({
                    current_stage: "compliance_checked",
                    items: [
                        {
                            id: "r1",
                            stage: "compliance_checked",
                            checks: [],
                            manual_checks: [{ id: "anonymization.visual_inspection", detail: "inspect figures by eye", source: null }],
                            limitations: [],
                            source_hashes: {},
                            artifact_id: "a",
                            assessor: "u",
                            assessor_version: "rp-readiness/1",
                            created_at: "2026-10-18T01:00:00Z",
                        },
                    ],
                })}
                projectId="p"
                canEdit={false}
                onChanged={() => {}}
            />,
        );
        const steps = within(screen.getByTestId("readiness-stepper")).getAllByRole("listitem");
        expect(steps).toHaveLength(7);
        expect(steps.filter((s) => s.getAttribute("data-reached") === "true")).toHaveLength(5);
        expect(steps[4].getAttribute("aria-current")).toBe("step");
        expect(screen.getByTestId("manual-checks").textContent).toContain("anonymization.visual_inspection");
    });
});
