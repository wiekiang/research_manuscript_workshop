import { readFileSync } from "node:fs";
import { join } from "node:path";
import { type Page, expect, test } from "@playwright/test";
import { createProject, field, registerAndOnboard } from "./helpers";
import { makeZip } from "./zip";

const FIXTURES = join(__dirname, "..", "fixtures", "templates");

async function uploadTemplate(page: Page, projectId: string, name: string, buffer: Buffer) {
    await page.goto(`/projects/${projectId}/templates`);
    await page.getByRole("tab", { name: "Upload the official ZIP" }).click();
    await page.getByLabel("Template archive (ZIP, up to 50 MB)").setInputFiles({ name, mimeType: "application/zip", buffer });
    await field(page, "Official origin URL").fill("https://mirrors.ctan.org/macros/latex/contrib/acmart.zip");
    await page.getByRole("textbox", { name: /How you obtained it/ }).fill("Official ACM consolidated template distribution (CTAN).");
    await field(page, "License or reuse note (as stated by the source)").fill("LPPL 1.3c");
    await page.getByText("This is the official template from the conference, organizer or publisher").click();
    await page.getByRole("button", { name: "Upload and analyse" }).click();
    await expect(page.getByText(/Template stored/).or(page.getByRole("alert").filter({ hasText: /\S/ }))).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText(/Template stored/)).toBeVisible();
}

test("M3: official template upload → safe analysis → three sandboxed sample compiles → confirmed", async ({ page }) => {
    test.setTimeout(300_000);
    await registerAndOnboard(page);
    const id = await createProject(page, "Template validation project");
    await uploadTemplate(page, id, "acmart.zip", readFileSync(join(FIXTURES, "acmart.zip")));

    const card = page.getByTestId("template-card").first();
    await expect(card).toHaveAttribute("data-status", "validated", { timeout: 240_000 });
    await expect(card.getByTestId("compile-run")).toHaveCount(3, { timeout: 240_000 });
    for (const run of await card.getByTestId("compile-run").all()) {
        await expect(run).toHaveAttribute("data-status", "compiled");
        await expect(run.getByText("Protected template files unchanged")).toBeVisible();
    }
    await expect(card.getByText("Can support a submission-ready package")).toBeVisible();
    await expect(card.getByText("No identifying content (text, metadata, sources, file names)")).toBeVisible();
    await expect(card.getByRole("button", { name: "Preview PDF" }).first()).toBeVisible();
    await card.getByText(/Protected template files \(\d+\)/).click();
    await expect(card.getByTestId("protected-files").getByText("acmart/acmart.dtx")).toBeVisible();

    await card.getByText("I have read this declaration and it is true for this template").click();
    await card.getByRole("button", { name: "Confirm template" }).click();
    await expect(card).toHaveAttribute("data-status", "confirmed");
    await expect(card.getByRole("status", { name: /Confirmed by you/ }).first()).toBeVisible();
});

test("M3: an archive with path traversal is rejected and cannot be confirmed", async ({ page }) => {
    test.setTimeout(180_000);
    await registerAndOnboard(page);
    const id = await createProject(page, "Unsafe template project");
    await uploadTemplate(page, id, "evil.zip", makeZip({ "../../escape.sty": "\\relax" }));
    const card = page.getByTestId("template-card").first();
    await expect(card).toHaveAttribute("data-status", "rejected", { timeout: 120_000 });
    await expect(card.getByText(/traversal/)).toBeVisible();
    await expect(card.getByText("Not submission-ready")).toBeVisible();
    await expect(card.getByRole("button", { name: "Confirm template" })).toBeDisabled();
});

test("M2: research profile + discovery reports the registry state honestly", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Discovery project");
    await page.goto(`/projects/${id}/discovery`);
    // Without topics the API refuses and the UI says what to do next.
    await page.getByRole("button", { name: "Run discovery" }).click();
    await expect(page.getByTestId("discovery-error")).toContainText("Your research profile has no topics yet.");

    const topics = page.getByRole("group", { name: "Research topics" });
    await topics.getByRole("textbox").fill("provenance capture");
    await topics.getByRole("textbox").press("Enter");
    await expect(topics.getByText("provenance capture")).toBeVisible();
    await page.getByRole("button", { name: "Save profile" }).click();
    await expect(page.getByText("Profile saved.")).toBeVisible();

    await page.getByRole("button", { name: "Run discovery" }).click();
    const empty = page.getByText("The curated official-source registry has no verified sources yet.");
    const progress = page.getByRole("heading", { name: "Discovery processing" });
    await expect(empty.or(progress)).toBeVisible();
    if (await empty.isVisible()) {
        await expect(page.getByRole("link", { name: "Import a CFP URL" })).toBeVisible();
    }
    await page.goto("/conferences/registry");
    await expect(page.getByRole("heading", { name: "Official-source registry", level: 1 })).toBeVisible();
});
