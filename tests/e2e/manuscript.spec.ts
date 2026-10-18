import { expect, test } from "@playwright/test";
import { createProject, registerAndOnboard } from "./helpers";

test("manuscript workspace starts empty and shows the server's refusal to draft before research is active", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Manuscript empty-state project");
    await page.goto(`/projects/${id}/manuscript`);
    await expect(page.getByTestId("manuscript-empty")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Manuscript completion" })).toBeVisible();
    // No manuscript, candidates or bibliography are invented.
    await expect(page.getByTestId("manuscript-span")).toHaveCount(0);
    await expect(page.getByTestId("candidate-row")).toHaveCount(0);

    await page.getByRole("button", { name: "Request draft" }).click();
    const alert = page.getByRole("alert").filter({ hasText: "drafting starts once research is active (project is CREATED)" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Error code wrong_state");
    await page.reload();
    await expect(page.getByTestId("manuscript-empty")).toBeVisible();
});

test("study type selection is recorded and the protocol refuses drafting before H1", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Method selection project");
    await page.goto(`/projects/${id}/direction`);
    await expect(page.getByText("H1 is recorded in direction review; the project is in CREATED.")).toBeVisible();

    await page.getByRole("combobox", { name: "Study type", exact: true }).selectOption("empirical_quantitative");
    await page.getByRole("combobox", { name: "Venue submission category" }).selectOption("full_paper");
    await page.getByRole("button", { name: "Select study type" }).click();
    // Without a target track the category's acceptance is unknown, so the API requires the researcher's rationale.
    await expect(page.getByRole("alert").filter({ hasText: "Error code rationale_required" })).toBeVisible();
    await page.getByRole("textbox", { name: "Rationale" }).fill("No target track yet; a full paper fits the planned scope.");
    await page.getByRole("button", { name: "Select study type" }).click();
    const instance = page.getByTestId("method-instance");
    await expect(instance).toBeVisible();
    await expect(instance).toContainText("Full paper");

    await page.goto(`/projects/${id}/methodology`);
    await expect(page.getByText("Record H1 before drafting the protocol.")).toBeVisible();
    await expect(page.getByTestId("method-stage").first()).toHaveAttribute("data-status", "blocked_until_h2");
    await page.getByRole("button", { name: "Save protocol version" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "record the H1 research direction before drafting the protocol" })).toBeVisible();
    await expect(page.getByTestId("protocol-version")).toHaveCount(0);
});
