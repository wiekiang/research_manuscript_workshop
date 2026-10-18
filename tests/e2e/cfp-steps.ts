import path from "node:path";
import { type Locator, type Page, expect } from "@playwright/test";
import { field } from "./helpers";

export const FIXTURE_CFP = path.resolve(__dirname, "../../services/research/src/rp_research/fixtures/cfp/icrds2027.html");

export async function supplyFixtureCfp(page: Page) {
    await page.getByRole("tab", { name: "Supply the official document" }).click();
    await page.locator("#cfp-file").setInputFiles(FIXTURE_CFP);
    await field(page, "Where it came from (official URL)").fill("https://icrds2027.example.org/cfp");
    await field(page, "How you obtained it").fill("Saved from the organizer's official CFP page (fixture).");
    await page.getByText("This is the official CFP or policy text from the organizer or publisher").click();
    await page.getByRole("button", { name: "Upload and extract" }).click();
    await expect(page.getByTestId("cfp-task").first()).toHaveAttribute("data-state", "succeeded", { timeout: 90_000 });
    await expect(page.getByTestId("rule-length.page_limit").first()).toBeVisible({ timeout: 30_000 });
}

export async function selectResearchTrack(page: Page) {
    await page.getByRole("button", { name: "Select target track" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("combobox", { name: "Track" }).selectOption({ label: "Research Papers Track" });
    await dialog.getByText("The snapshot comes from the organizer's official CFP page").click();
    await dialog.getByRole("button", { name: "Select target" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(/Target \(official\): Research Papers Track/)).toBeVisible();
}

async function resolveOne(page: Page, item: Locator) {
    const testId = (await item.getAttribute("data-testid")) ?? "";
    await item.getByRole("button", { name: /^Resolve/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const decision = dialog.getByRole("combobox", { name: "Decision" });
    if (testId === "rule-fees.statement") {
        await decision.selectOption("reject");
        await field(page, "Rationale").fill("The official CFP does not mention a registration fee.");
    } else if (testId === "deadline-full_paper") {
        await decision.selectOption("edit");
        await field(page, "Date (YYYY-MM-DD)").fill("2027-01-21");
        await field(page, "Timezone").fill("AoE");
        await field(page, "Rationale").fill("The source states January 21, 2027 (AoE).");
    } else if (testId.startsWith("deadline-")) {
        await decision.selectOption("confirm");
        await field(page, "Timezone").fill("AoE");
        await field(page, "Rationale").fill("Organizers state all deadlines are Anywhere on Earth.");
    } else {
        await decision.selectOption("confirm");
        await field(page, "Rationale").fill("Checked against the official source sentence.");
    }
    await dialog.getByRole("button", { name: "Record resolution" }).click();
    await expect(dialog).toBeHidden();
}

export async function resolveAllOpenItems(page: Page) {
    for (let i = 0; i < 40; i++) {
        const open = page.locator('[data-status="needs_human_resolution"][data-testid^="rule-"], [data-status="needs_human_resolution"][data-testid^="deadline-"]');
        if ((await open.count()) === 0) return;
        await resolveOne(page, open.first());
        await page.waitForTimeout(300);
    }
    throw new Error("open CFP items did not converge");
}

