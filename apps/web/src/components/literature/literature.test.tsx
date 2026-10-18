import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StudyTypeRecommendation } from "@/components/opportunities/opportunity-card";
import { VerificationMethodLabel } from "@/components/research/verification-method-label";
import type { CoverageAssessment, StudyTypeRec } from "@/lib/api/types";
import { identityLabel, safeCoverageLevel, verificationProvider } from "@/lib/literature";
import { CoverageReport } from "./coverage-report";
import { IdentityBadge } from "./papers-panel";

describe("identity badge mapping", () => {
    it("never softens an unregistered DOI", () => {
        const l = identityLabel("not_found", { outcome: "fail", source: "crossref" });
        expect(l.label).toBe("DOI not registered — possible fabricated or mistyped DOI");
        expect(l.status).toBe("identity_not_found");
        render(<IdentityBadge paper={{ identity_status: "not_found", identity_verification: { outcome: "fail", source: "crossref" } }} />);
        expect(screen.getByText("DOI not registered — possible fabricated or mistyped DOI")).toBeInTheDocument();
    });

    it("distinguishes an unavailable registry from a missing DOI", () => {
        const l = identityLabel("unverified", { outcome: "unavailable" });
        expect(l.status).toBe("identity_unavailable");
        expect(l.label).not.toMatch(/not registered/);
        expect(identityLabel("verified", { outcome: "pass", source: "crossref" }).label).toBe("Identity verified");
    });
});

describe("verification method labels", () => {
    it("never renders a model-assisted record as human", () => {
        const v = { method: "model_assisted", verifier: "fixture:fixture-model", evidence: {} };
        expect(verificationProvider(v)).toBe("fixture");
        render(<VerificationMethodLabel method="model_assisted" provider={verificationProvider(v)} />);
        expect(screen.getByText(/Model-assisted/)).toBeInTheDocument();
        expect(screen.getByText(/Fixture output \(test\/demo only\)/)).toBeInTheDocument();
        expect(screen.queryByText("Human")).toBeNull();
    });

    it("gives no provider to deterministic or human records", () => {
        expect(verificationProvider({ method: "deterministic", verifier: "passage_locator", evidence: {} })).toBeNull();
        expect(verificationProvider({ method: "human", verifier: "user:1", evidence: {} })).toBeNull();
    });
});

describe("coverage report", () => {
    const message = "Searched Crossref for 1 query on 2026-10-18. Reviewed 1 full text and 0 abstracts. This review may miss relevant work.";
    const cov: CoverageAssessment = {
        version: 2,
        artifact_id: "a1",
        counts: {
            sources_queried: ["crossref"], unavailable_sources: [], queries: [{ query: "provenance", filters: {}, executed_at: "2026-10-18", providers: {} }],
            retrieved_records: 4, unique_records: 3, papers_total: 3, manual_or_uploaded: 1, fulltext_reviewed: 1, abstract_only: 0, metadata_only: 2,
            fulltext_inaccessible_or_not_permitted: 0, screened: 0, included: 0, excluded: 0, exclusion_reasons: [],
            papers_contributing_verified_evidence: 1, identity_verified: 1, identity_problems: 0,
        },
        coverage_level: "comprehensive",
        rationale: "Treat as comprehensive coverage.",
        limitations: ["Only Crossref was searched."],
        message,
    };

    it("renders the backend message verbatim and never claims comprehensive coverage", () => {
        const { container } = render(<CoverageReport projectId="p1" cov={cov} />);
        expect(screen.getByTestId("coverage-message").textContent).toBe(message);
        expect(container.textContent).not.toMatch(/comprehensive/i);
        expect(safeCoverageLevel("comprehensive")).toBe("limited");
        expect(screen.getByText("Records retrieved across searches").closest("a")).toHaveAttribute("href", "/projects/p1/literature#search-history");
        expect(screen.getByText("Full texts reviewed").closest("a")).toHaveAttribute("href", "/projects/p1/literature?filter=fulltext#papers");
    });
});

describe("study type recommendation", () => {
    it("renders study type and venue category as separate fields", () => {
        const rec: StudyTypeRec = {
            id: "s1", study_type: "systematic_literature_review", venue_category: "full_research_paper", fit_rationale: "Fits the gap.",
            track_accepts: "yes", track_rule_ref: {}, required_inputs: [], reporting_standard: "PRISMA 2020", blockers: [],
            method_enabled: false, method_availability: "planning_only", advisory: true,
        };
        render(<StudyTypeRecommendation rec={rec} />);
        const card = screen.getByTestId("study-type-rec");
        const st = within(card).getByTestId("rec-study-type");
        const vc = within(card).getByTestId("rec-venue-category");
        expect(st).not.toBe(vc);
        expect(vc.textContent).toBe("full research paper");
        expect(st.textContent).not.toMatch(/research paper/);
        expect(within(card).getByText("Planning only in this release")).toBeInTheDocument();
    });
});
