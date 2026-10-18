import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { createProject, field, registerAndOnboard } from "./helpers";

const FIXTURE_PAPER = join(__dirname, "..", "..", "services/research/src/rp_research/fixtures/papers/provenance-pipelines.txt");
const PAPER_DOI = "10.14778/3415478.3415556";
const PAPER_TITLE = "Improving reproducibility of data science pipelines";
const FABRICATED_DOI = "10.9999/fabricated.doi.2025.00001";

test.describe.configure({ timeout: 300_000 });

test("uploaded paper yields verified passages, an extracted claim and a labelled model-assisted verification", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Literature evidence project");
    await page.goto(`/projects/${id}/literature`);
    await expect(page.getByTestId("literature-setup-message")).toBeVisible();

    await page.getByRole("button", { name: "Upload paper" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.locator("#paper-file").setInputFiles(FIXTURE_PAPER);
    await field(dialog, "DOI").fill(PAPER_DOI);
    await field(dialog, "Title").fill(PAPER_TITLE);
    await field(dialog, "Rights statement").fill("Author-provided fixture copy for automated tests.");
    await dialog.getByText("I have the right to use this file for this project").click();
    await dialog.getByRole("button", { name: "Upload paper" }).click();
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    await expect(page.getByTestId("paper-row")).toHaveCount(1);

    await page.goto(`/projects/${id}/evidence`);
    await expect(page.locator('[data-testid="passage"][data-verified="true"]')).toHaveCount(3, { timeout: 180_000 });
    const claimRow = page.locator('[data-testid="claim-row"][data-category="descriptive"]');
    await expect(claimRow.first()).toBeVisible({ timeout: 60_000 });

    await claimRow.first().getByRole("button", { name: "Details" }).click();
    const detail = page.getByTestId("claim-detail");
    await expect(detail).toBeVisible();
    await detail.getByRole("button", { name: "Verify" }).click();
    await detail.getByText("Request a model-assisted support assessment of the linked passages").click();
    await detail.getByRole("button", { name: "Record and re-evaluate" }).click();

    const record = detail.locator('[data-testid="verification-record"][data-method="model_assisted"]');
    await expect(record.first()).toBeVisible({ timeout: 180_000 });
    await expect(record.first()).toContainText("Model-assisted");
    await expect(record.first()).toContainText("Fixture output (test/demo only)");
    await expect(detail.locator('[data-testid="verification-record"][data-method="human"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="claim-row"][data-category="descriptive"][data-status="verified"]').first()).toBeVisible({ timeout: 60_000 });
});

test("a fabricated DOI is reported as not registered", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Fabricated DOI project");
    await page.goto(`/projects/${id}/literature`);
    await page.getByRole("button", { name: "Add citation" }).first().click();
    const dialog = page.getByRole("dialog");
    await field(dialog, "DOI").fill(FABRICATED_DOI);
    await field(dialog, "Title").fill("A study that does not exist");
    await dialog.getByRole("button", { name: "Add citation" }).click();
    await expect(dialog).toBeHidden({ timeout: 30_000 });
    const row = page.getByTestId("paper-row").first();
    // With network access the registry reports the DOI missing; without it the check is honestly "unavailable".
    await expect(row).toHaveAttribute("data-identity", /not_found|unverified/, { timeout: 120_000 });
    await expect(
        row.getByText("DOI not registered — possible fabricated or mistyped DOI").or(row.getByText("Identity check unavailable")),
    ).toBeVisible({ timeout: 120_000 });
});

test("the coverage report states what was searched and that work may be missed", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Coverage project");
    await page.goto(`/projects/${id}/literature/coverage`);
    const msg = page.getByTestId("coverage-message");
    await expect(msg).toContainText(/Searched/);
    await expect(msg).toContainText("This review may miss relevant work.");
    await expect(page.getByText(/comprehensive/i)).toHaveCount(0);
});
