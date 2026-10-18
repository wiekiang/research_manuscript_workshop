import { expect, test } from "@playwright/test";
import { resolveAllOpenItems, selectResearchTrack, supplyFixtureCfp } from "./cfp-steps";
import { createProject, registerAndOnboard } from "./helpers";

test("M0.4 journey: supplied CFP → source-linked rules → human resolution → CFP gate → DIRECTION_REVIEW", async ({ page }) => {
    await registerAndOnboard(page);
    const projectId = await createProject(page, "Reproducible provenance capture");
    await supplyFixtureCfp(page);

    // Evidence is visible next to each rule: quote, locator, methods and the fixture label.
    const pageLimit = page.getByTestId("rule-length.page_limit").filter({ hasText: "Research Papers Track" });
    await expect(pageLimit.getByText(/Section: .*Research Papers Track/)).toBeVisible();
    await expect(pageLimit.getByText("Deterministic", { exact: true })).toBeVisible();
    await expect(page.getByText(/Fixture output \(test\/demo only\)/).first()).toBeVisible();
    await expect(page.getByTestId("rule-fees.statement")).toHaveAttribute("data-status", "needs_human_resolution");

    await selectResearchTrack(page);

    // Ambiguous rules block the gate: the signature control is disabled while items are open.
    const consent = page.getByRole("checkbox", { name: "I have read this declaration and it is true for me" });
    await expect(consent).toBeDisabled();

    await resolveAllOpenItems(page);
    await expect(page.getByTestId("deadline-full_paper")).toContainText("2027-01-21");

    // Sign the CFP gate with the keyboard only.
    await expect(consent).toBeEnabled({ timeout: 15_000 });
    await consent.focus();
    await page.keyboard.press("Space");
    await expect(consent).toBeChecked();
    const confirm = page.getByRole("button", { name: "Confirm CFP rules" });
    for (let i = 0; i < 6 && !(await confirm.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
    await expect(confirm).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("CFP rules confirmed. The project is now in Direction review (H1).")).toBeVisible();

    await page.goto(`/projects/${projectId}/activity`);
    const timeline = page.getByTestId("event-timeline");
    await expect(timeline.getByText("Created → Target review")).toBeVisible();
    await expect(timeline.getByText("Target review → Direction review (H1)")).toBeVisible();

    await page.goto(`/projects/${projectId}`);
    await expect(page.getByRole("list").getByText("Direction review (H1)").first()).toBeVisible();
    await expect(page.getByText("CFP: Track and CFP rules")).toBeVisible();
});
