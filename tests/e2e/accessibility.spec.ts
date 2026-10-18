import { expect, test } from "@playwright/test";
import { selectResearchTrack, supplyFixtureCfp } from "./cfp-steps";
import { createProject, registerAndOnboard } from "./helpers";

test("keyboard navigation and accessible status names in the CFP workspace", async ({ page }) => {
    await registerAndOnboard(page);
    await createProject(page, "Keyboard navigation project");

    // Skip link is the first stop and moves focus to the main region.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();

    await supplyFixtureCfp(page);
    await selectResearchTrack(page);

    // Status badges expose text, not just color.
    await expect(page.getByRole("status", { name: /^Status: Needs your resolution/ }).first()).toBeVisible();
    await expect(page.getByRole("status", { name: /^Status: Cross-checked/ }).first()).toBeVisible();

    // The resolution dialog opens from the keyboard, traps focus and closes with Escape.
    const resolve = page.getByRole("button", { name: /^Resolve Fees statement/ });
    await resolve.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: /Resolve: Fees statement/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(resolve).toBeFocused();

    // Import method tabs are reachable and operable by keyboard.
    const fileTab = page.getByRole("tab", { name: "Supply the official document" });
    await fileTab.focus();
    await expect(fileTab).toHaveAttribute("aria-selected", "true");
    const urlTab = page.getByRole("tab", { name: "Import from the official URL" });
    await urlTab.focus();
    await page.keyboard.press("Enter");
    await expect(urlTab).toHaveAttribute("aria-selected", "true");
});
