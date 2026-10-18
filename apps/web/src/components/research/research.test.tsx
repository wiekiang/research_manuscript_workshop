import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { COPY } from "@/lib/copy";
import copyJson from "../../../../../contracts/schemas/copy.json";
import { ApprovalPanel } from "./approval-panel";
import { NextActionPanel } from "./next-action-panel";
import { StageTimeline } from "./stage-timeline";
import { StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
    it.each([
        ["waiting_human", "Waiting for you"],
        ["blocked", "Blocked"],
        ["stale", "Stale"],
        ["complete", "Complete"],
        ["needs_human_resolution", "Needs your resolution"],
        ["validated", "Cross-checked"],
        ["confirmed", "Confirmed by you"],
        ["rejected", "Rejected"],
        ["failed", "Failed"],
        ["running", "Running"],
        ["queued", "Queued"],
    ])("renders %s as a text label with an accessible name", (status, label) => {
        render(<StatusBadge status={status} />);
        expect(screen.getByText(label)).toBeInTheDocument();
        expect(screen.getByRole("status", { name: new RegExp(`^Status: ${label}`) })).toBeInTheDocument();
    });
});

describe("ApprovalPanel", () => {
    const declaration = "I confirm the selected conference track and that I have checked each blocking rule.";

    it("shows the exact declaration and stays disabled until the box is checked", async () => {
        const onSubmit = vi.fn().mockResolvedValue(undefined);
        render(<ApprovalPanel gate="CFP" title="Confirm" declaration={declaration} onSubmit={onSubmit} submitLabel="Confirm CFP rules" />);
        expect(screen.getByTestId("declaration-CFP")).toHaveTextContent(declaration);
        const button = screen.getByRole("button", { name: "Confirm CFP rules" });
        expect(button).toBeDisabled();
        await userEvent.click(screen.getByText("I have read this declaration and it is true for me"));
        expect(button).toBeEnabled();
        await userEvent.click(button);
        expect(onSubmit).toHaveBeenCalledWith({ declaration_accepted: true, declaration_text: declaration, rationale: undefined });
    });

    it("cannot be signed while blocking reasons remain", () => {
        render(<ApprovalPanel gate="H1" title="Direction" declaration={declaration} blockingReasons={["resolve deadline.full_paper"]} onSubmit={vi.fn()} />);
        expect(screen.getByText("resolve deadline.full_paper")).toBeInTheDocument();
        expect(screen.getByRole("checkbox")).toBeDisabled();
        expect(screen.getByRole("button", { name: "Sign H1" })).toBeDisabled();
    });
});

describe("NextActionPanel", () => {
    it("lists failing gate reasons with a direct action", () => {
        render(
            <NextActionPanel
                projectId="p1"
                state="TARGET_REVIEW"
                nextStep={{
                    target_state: "DIRECTION_REVIEW",
                    description: "Official CFP snapshot exists",
                    gates: [{ gate_id: "cfp.confirmed", passed: false, reasons: ["resolve deadline.rebuttal: timezone not stated"], evidence: {}, next_action: null }],
                    ready: false,
                }}
            />,
        );
        expect(screen.getByText("resolve deadline.rebuttal: timezone not stated")).toBeInTheDocument();
        expect(screen.getAllByText("Resolve and confirm CFP rules")[0]).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Resolve and confirm CFP rules" })).toHaveAttribute("href", "/projects/p1/cfp");
    });
});

describe("StageTimeline", () => {
    it("names the current stage in text and marks human gates", () => {
        render(<StageTimeline state="DIRECTION_REVIEW" />);
        expect(screen.getByText("(current stage)")).toBeInTheDocument();
        expect(screen.getAllByText("human gate")).toHaveLength(5);
    });
});

describe("required copy", () => {
    it("is byte-identical to contracts/schemas/copy.json", () => {
        expect(COPY).toEqual(copyJson);
        expect(COPY.home_headline).toBe("From Call for Papers to Submission-Ready Manuscripts.");
        expect(COPY.responsibility_message).toBe(
            "Our platform helps with discovery, evidence review, research planning, manuscript development, and conference checks. You are responsible for the originality, validity, and integrity of your contribution.",
        );
    });
});
