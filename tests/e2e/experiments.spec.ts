import { expect, test } from "@playwright/test";
import { createProject, field, registerAndOnboard } from "./helpers";

test("experiments: honest empty state, plan form uses the project's own files, h2_required refusal shown verbatim", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Experiment planning project");

    // Upload a code file as a contribution so the plan form can reference it.
    await page.goto(`/projects/${id}/contributions`);
    await page.getByRole("button", { name: "Add a contribution" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.locator("#contribution-file").setInputFiles({ name: "main.py", mimeType: "text/x-python", buffer: Buffer.from("print('hello')\n") });
    await dialog.getByLabel("Type").selectOption("code");
    await field(dialog, "Title").fill("Restoration classifier code");
    await field(dialog, "Rights statement").fill("Written by me for this study.");
    await dialog.getByRole("button", { name: "Save contribution" }).click();
    await expect(page.getByTestId("contribution-row").filter({ hasText: "Restoration classifier code" })).toBeVisible();

    await page.goto(`/projects/${id}/experiments`);
    await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
    await expect(page.getByTestId("experiments-empty")).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);

    await page.getByRole("button", { name: "New experiment plan" }).click();
    const form = page.getByRole("dialog");
    const save = form.getByRole("button", { name: "Save draft plan" });
    await expect(save).toBeDisabled();
    await field(form, "Title").fill("Restoration classifier on eight pipelines");
    await form.getByLabel("Code file (from your contributions)").selectOption({ label: "Restoration classifier code (code)" });
    await expect(form.getByLabel("Sandbox image")).toHaveValue("python-sci:1");
    await expect(field(form, "Argument 4")).toHaveValue("{seed}");
    await expect(save).toBeDisabled();
    await field(form, "Data origin").fill("eight public R pipelines");
    await field(form, "Data rights").fill("public source code (MIT/GPL)");
    await field(form, "Limitations").fill("small exploratory sample");
    await expect(save).toBeEnabled();
    await save.click();

    // Without an H2-frozen protocol the server refuses; its message is shown word for word with a hint.
    await expect(form.getByRole("alert")).toContainText("experiments run only under an H2-frozen protocol");
    await expect(form.getByRole("alert")).toContainText("h2_required");
    await expect(form.getByText("Freeze a protocol at H2 first (Methodology & protocol).", { exact: false })).toBeVisible();
    await form.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByTestId("experiment-plan")).toHaveCount(0);
});
