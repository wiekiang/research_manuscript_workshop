import { expect, test } from "@playwright/test";
import { createProject, registerAndOnboard } from "./helpers";

test("review and integrity workspaces start empty and show the server's refusal before scientific review", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Review empty-state project");

    await page.goto(`/projects/${id}/review`);
    await expect(page.getByRole("heading", { name: "Independent review" })).toBeVisible();
    await expect(page.getByTestId("review-empty")).toBeVisible();
    // Nothing is invented: no reports, findings or scores.
    await expect(page.getByTestId("review-report")).toHaveCount(0);
    await expect(page.getByTestId("finding")).toHaveCount(0);
    await expect(page.getByText("there is no score and no prediction of acceptance", { exact: false })).toBeVisible();
    await expect(page.getByText(/score\s*[:=]|acceptance (probability|likelihood)/i)).toHaveCount(0);
    await expect(page.getByTestId("gate-panel-COMPLIANCE_REVIEW")).toContainText("Evaluated in Scientific review");

    await page.getByRole("button", { name: "Run review on the current version" }).click();
    const alert = page.getByRole("alert").filter({ hasText: "independent review runs once the manuscript is complete (project is CREATED)" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Error code wrong_state");

    await page.goto(`/projects/${id}/integrity`);
    await expect(page.getByTestId("integrity-empty")).toBeVisible();
    await page.getByRole("button", { name: "Run integrity checks" }).click();
    const ialert = page.getByRole("alert").filter({ hasText: "integrity checks run on a complete manuscript (project is CREATED)" });
    await expect(ialert).toBeVisible();
    await expect(page.getByTestId("integrity-check")).toHaveCount(0);
});
