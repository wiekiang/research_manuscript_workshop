import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ruleModelProvider } from "@/components/cfp/rules-list";
import { confirmBlockReason, templateLabel } from "@/components/templates/template-status";
import type { CfpRule, CompileRunEntry } from "@/lib/api/types";
import { ScoreBreakdown, formatComponentScore } from "./score-breakdown";

describe("ScoreBreakdown", () => {
    it("renders a missing score as 'unknown', never as 0", () => {
        expect(formatComponentScore(null)).toBe("unknown");
        expect(formatComponentScore(undefined)).toBe("unknown");
        expect(formatComponentScore(0)).toBe("0%");
        render(
            <ScoreBreakdown
                total={0.62}
                components={[
                    { name: "topic_fit", score: 0.56, uncertainty: "lexical coverage", evidence: ["shared terms: provenance"] },
                    { name: "cost", score: null, uncertainty: "no travel budget in profile", evidence: [] },
                ]}
            />,
        );
        const cost = screen.getByTestId("component-cost");
        expect(within(cost).getByText("unknown")).toBeInTheDocument();
        expect(within(cost).queryByText("0%")).toBeNull();
        expect(within(cost).getByText("no travel budget in profile")).toBeInTheDocument();
        expect(within(screen.getByTestId("component-topic_fit")).getByText("56%")).toBeInTheDocument();
        expect(screen.getByText(/not a reputation score/)).toBeInTheDocument();
    });
});

describe("template status mapping", () => {
    const run = (status: string): CompileRunEntry => ({
        id: "r", kind: "sample", options: {}, status, pages: 1, checks: [], errors: [], freshness: "current", created_at: "",
        pdf_artifact_id: null, report_artifact_id: null, log_artifact_id: null, source_bundle_artifact_id: null, manuscript_version_id: null,
    });

    it("labels unsupported templates as not submission-ready", () => {
        expect(templateLabel({ label: "not_submission_ready", supported: false }).text).toBe("Not submission-ready");
        expect(templateLabel({ label: "submission_ready_capable", supported: true }).tone).toBe("ok");
    });

    it("blocks confirmation until a clean sample compile exists", () => {
        expect(confirmBlockReason({ supported: false, status: "unsupported", compile_runs: [] })).toMatch(/cannot be confirmed/);
        expect(confirmBlockReason({ supported: true, status: "validated", compile_runs: [run("failed")] })).toMatch(/clean sample compile/);
        expect(confirmBlockReason({ supported: true, status: "validated", compile_runs: [run("compiled")] })).toBeNull();
        expect(confirmBlockReason({ supported: true, status: "confirmed", compile_runs: [run("compiled")] })).toMatch(/Already/);
    });
});

describe("rule provenance", () => {
    it("takes the fixture label from the rule's own model-assisted observation", () => {
        const rule = {
            observations: [
                { method: "deterministic", provider: null },
                { method: "model_assisted", provider: "fixture" },
            ],
            second_pass: {},
        } as unknown as CfpRule;
        expect(ruleModelProvider(rule)).toBe("fixture");
        expect(ruleModelProvider({ observations: [], second_pass: { provider: "anthropic" } } as unknown as CfpRule)).toBe("anthropic");
        expect(ruleModelProvider({ observations: [], second_pass: {} } as unknown as CfpRule)).toBeNull();
    });
});
