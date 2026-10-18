import { expect, test } from "@playwright/test";
import { createProject, registerAndOnboard } from "./helpers";

const FAKE_KEY = "sk-ant-test-" + "x".repeat(32);

test("AI provider: options shown with reasons, own API key connects showing only its hint, project can select it, disconnect", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "AI provider choice project");

    await expect(page.getByTestId("provider-badge")).toHaveText("AI provider: not chosen");
    await page.goto(`/projects/${id}/costs`);
    const card = page.getByRole("radiogroup", { name: "AI provider for this project" });
    await expect(card.getByRole("radio", { name: /Claude login on this computer/ })).toBeVisible();
    await expect(card.getByRole("radio", { name: /Recorded test responses/ })).toBeVisible();
    // The dev API runs locally, so the CLI-login option is offered; the API-key option needs a connected key.
    await expect(card.getByRole("radio", { name: /My Anthropic API key/ })).toBeDisabled();
    await expect(page.getByTestId("provider-reason-anthropic")).toHaveText("Not available: connect your Anthropic API key in account settings first");

    // Connect an obviously fake but well-formed key; only its hint is ever shown afterwards.
    await page.goto("/settings");
    const keyInput = page.getByLabel("API key");
    await keyInput.fill(FAKE_KEY);
    await page.getByText("I accept this statement").click();
    await page.getByRole("button", { name: "Connect key" }).click();
    await expect(page.getByText("Connected (key …xxxx)")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(FAKE_KEY);

    // The project can now select it; the data-flow approval is still required and offered.
    await page.goto(`/projects/${id}/costs`);
    const anthropic = card.getByRole("radio", { name: /My Anthropic API key/ });
    await expect(anthropic).toBeEnabled();
    await card.getByText("My Anthropic API key", { exact: true }).click();
    await expect(page.getByTestId("provider-option-anthropic")).toContainText("Selected");
    await expect(page.getByTestId("data-flow-cta")).toContainText("My Anthropic API key");
    await expect(page.getByTestId("provider-badge")).toHaveText("AI provider: My Anthropic API key");
    await page.getByRole("button", { name: "Approve the data flow for this provider" }).click();
    await expect(page.getByRole("dialog").getByLabel("Model provider")).toHaveValue("anthropic");
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();

    // Disconnect: the stored key is destroyed and the option becomes unavailable again for new choices.
    await page.goto("/settings");
    await page.getByRole("button", { name: "Disconnect key" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Disconnect" }).click();
    await expect(page.getByText("Not connected")).toBeVisible();
    await page.goto(`/projects/${id}/costs`);
    await expect(page.getByTestId("provider-reason-anthropic")).toHaveText("Not available: connect your Anthropic API key in account settings first");
});
