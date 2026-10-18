import { expect, test } from "@playwright/test";
import { createProject, registerAndOnboard } from "./helpers";

test("evidence synthesis and qualitative workspaces: method-scoped navigation and honest setup states", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await registerAndOnboard(page);
    const id = await createProject(page, "Systematic review planning project");

    // Without a study type, the method-specific workspaces are not offered in project navigation.
    await page.goto(`/projects/${id}`);
    const nav = page.getByRole("navigation", { name: "Project workspaces" });
    await expect(nav.getByRole("link", { name: "Methodology & protocol" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Review workspace" })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Qualitative analysis" })).toHaveCount(0);

    // The review workspace explains, word for word, that it needs the H2-frozen specification (a notice, not an error).
    await page.goto(`/projects/${id}/review-workspace`);
    await expect(page.getByRole("heading", { name: "Review workspace" })).toBeVisible();
    const notice = page.getByTestId("synthesis-notice");
    await expect(notice).toContainText("the review specification is used only from the H2-frozen protocol");
    await expect(notice).toContainText("Code h2_required");
    await expect(notice).toHaveAttribute("role", "status");
    await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Run specified searches" })).toHaveCount(0);

    // The qualitative workspace shows an empty codebook and no coding actions before codes exist.
    await page.goto(`/projects/${id}/qualitative`);
    await expect(page.getByRole("heading", { name: "Qualitative analysis" })).toBeVisible();
    await expect(page.getByTestId("qual-empty-codes")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Source-to-code trace" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add coded segment" })).toHaveCount(0);
    await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);

    // Coverage is never described as comprehensive on these pages.
    await expect(page.getByText(/comprehensive/i)).toHaveCount(0);
    expect(pageErrors).toEqual([]);
});
