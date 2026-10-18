import type { ModelProviderKey, ModelProviderView } from "@/lib/api/types";

/** Neutral explanations shown under each provider option. The option labels themselves come from the API. */
export const PROVIDER_EXPLANATIONS: Record<ModelProviderKey, string> = {
    claude_cli:
        "Uses the Claude CLI that is logged in on the computer running the platform. Available only on a local install; usage counts against that Claude plan.",
    anthropic: "Uses the Anthropic API key connected in your account settings. Calls are billed to your Anthropic account.",
    fixture: "Replays recorded test responses for demos and automated tests. They are labelled as recorded and are not real model output.",
};

/** Short label for the project shell badge, so researchers know whether AI output is real or recorded. */
export function providerBadgeLabel(view: ModelProviderView | undefined): string {
    if (!view) return "AI provider: loading";
    if (!view.selected) return "AI provider: not chosen";
    const opt = view.options.find((o) => o.key === view.selected);
    return `AI provider: ${opt?.label ?? view.selected}`;
}

/** The selected real provider still needs the owner's data-flow approval before any call on project data. */
export function needsDataFlow(view: ModelProviderView | undefined): ModelProviderKey | null {
    if (!view?.selected || view.selected === "fixture") return null;
    const opt = view.options.find((o) => o.key === view.selected);
    return opt && !opt.data_flow_attested ? view.selected : null;
}

/** Browser event fired after a project's AI provider changes, so the shell badge refreshes without a reload. */
export const PROVIDER_CHANGED_EVENT = "rp:model-provider-changed";

export function announceProviderChange(projectId: string): void {
    if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(PROVIDER_CHANGED_EVENT, { detail: { projectId } }));
}
