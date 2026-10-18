import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { ModelProviderView } from "@/lib/api/types";
import { needsDataFlow, providerBadgeLabel } from "@/lib/model-provider";
import { AnthropicConnectionView } from "./model-connections-card";
import { ModelProviderChoice } from "./model-provider-card";

const CONSENT = "I am connecting my own Anthropic API key. (test consent)";
const KEY = "sk-ant-test-" + "x".repeat(32);

const view = (over: Partial<ModelProviderView> = {}): ModelProviderView => ({
    selected: null,
    can_change: true,
    note: "Each choice still needs the project owner's data-flow approval for that provider.",
    options: [
        { key: "claude_cli", label: "Claude login on this computer (local CLI)", available: false, reason: "available only when the platform runs locally on your own computer", data_flow_attested: false },
        { key: "anthropic", label: "My Anthropic API key", available: true, reason: null, data_flow_attested: false },
        { key: "fixture", label: "Recorded test responses (demo only)", available: true, reason: null, data_flow_attested: true },
    ],
    ...over,
});

describe("ModelProviderChoice", () => {
    it("keeps unavailable options visible but disabled, with the server's reason", () => {
        render(<ModelProviderChoice view={view()} onSelect={vi.fn()} />);
        const radio = screen.getByRole("radio", { name: /Claude login on this computer/ });
        expect(radio).toBeDisabled();
        expect(screen.getByTestId("provider-reason-claude_cli")).toHaveTextContent(
            "Not available: available only when the platform runs locally on your own computer",
        );
        expect(screen.getByRole("radio", { name: /My Anthropic API key/ })).not.toBeDisabled();
    });

    it("shows the data-flow call to action for a selected real provider that is not attested", () => {
        const onAttest = vi.fn();
        render(<ModelProviderChoice view={view({ selected: "anthropic" })} onSelect={vi.fn()} onAttest={onAttest} />);
        expect(screen.getByTestId("data-flow-cta")).toHaveTextContent("My Anthropic API key");
        fireEvent.click(screen.getByRole("button", { name: "Approve the data flow for this provider" }));
        expect(onAttest).toHaveBeenCalledWith("anthropic");
    });

    it("shows no data-flow call to action for recorded responses or an attested provider", () => {
        const { rerender } = render(<ModelProviderChoice view={view({ selected: "fixture" })} onSelect={vi.fn()} />);
        expect(screen.queryByTestId("data-flow-cta")).toBeNull();
        const attested = view({ selected: "anthropic" });
        attested.options[1].data_flow_attested = true;
        rerender(<ModelProviderChoice view={attested} onSelect={vi.fn()} />);
        expect(screen.queryByTestId("data-flow-cta")).toBeNull();
    });

    it("shows a provider_unavailable refusal verbatim", async () => {
        const onSelect = vi.fn().mockRejectedValue(new ApiError(422, "provider_unavailable", "connect your Anthropic API key in account settings first", null, "r1"));
        render(<ModelProviderChoice view={view()} onSelect={onSelect} />);
        fireEvent.click(screen.getByRole("radio", { name: /My Anthropic API key/ }));
        expect(await screen.findByRole("alert")).toHaveTextContent("connect your Anthropic API key in account settings first");
    });

    it("lets only the owner change the choice", () => {
        render(<ModelProviderChoice view={view({ can_change: false })} onSelect={vi.fn()} />);
        expect(screen.getByRole("radio", { name: /My Anthropic API key/ })).toBeDisabled();
        expect(screen.getByText("Only the project owner can change the AI provider.")).toBeInTheDocument();
    });
});

describe("AnthropicConnectionView", () => {
    it("never renders the key after submitting, and sends the exact consent text", async () => {
        const onConnect = vi.fn().mockResolvedValue(undefined);
        const { container } = render(<AnthropicConnectionView connection={{ connected: false, consent_text: CONSENT }} onConnect={onConnect} onDisconnect={vi.fn()} />);
        const input = container.querySelector('input[type="password"]') as HTMLInputElement;
        fireEvent.change(input, { target: { value: KEY } });
        fireEvent.click(screen.getByRole("checkbox", { name: "I accept this statement" }));
        fireEvent.click(screen.getByRole("button", { name: "Connect key" }));
        await waitFor(() => expect(onConnect).toHaveBeenCalledWith(KEY, CONSENT));
        expect(input.value).toBe("");
        expect(container.innerHTML).not.toContain(KEY);
    });

    it("clears the key and shows the refusal verbatim when the key is rejected", async () => {
        const onConnect = vi.fn().mockRejectedValue(new ApiError(422, "invalid_key_format", "this does not look like an Anthropic API key (it starts with sk-ant-)", null, "r2"));
        const { container } = render(<AnthropicConnectionView connection={{ connected: false, consent_text: CONSENT }} onConnect={onConnect} onDisconnect={vi.fn()} />);
        const input = container.querySelector('input[type="password"]') as HTMLInputElement;
        fireEvent.change(input, { target: { value: "not-a-real-key-at-all-xyz" } });
        fireEvent.click(screen.getByRole("checkbox", { name: "I accept this statement" }));
        fireEvent.click(screen.getByRole("button", { name: "Connect key" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("this does not look like an Anthropic API key (it starts with sk-ant-)");
        expect(input.value).toBe("");
    });

    it("shows only the key hint when connected", () => {
        render(<AnthropicConnectionView connection={{ connected: true, key_hint: "…xxxx", consent_text: CONSENT }} onConnect={vi.fn()} onDisconnect={vi.fn()} />);
        expect(screen.getByText("Connected (key …xxxx)")).toBeInTheDocument();
        expect(screen.queryByRole("textbox")).toBeNull();
    });
});

describe("provider helpers", () => {
    it("labels the badge and detects a missing data-flow approval", () => {
        expect(providerBadgeLabel(view())).toBe("AI provider: not chosen");
        expect(providerBadgeLabel(view({ selected: "fixture" }))).toBe("AI provider: Recorded test responses (demo only)");
        expect(needsDataFlow(view({ selected: "anthropic" }))).toBe("anthropic");
        expect(needsDataFlow(view({ selected: "fixture" }))).toBeNull();
    });
});
