import { expect, test } from "@playwright/test";
import { RESPONSIBILITY, createProject, field, registerAndOnboard } from "./helpers";

test("home and project setup show the exact human-contribution message", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("From Call for Papers to Submission-Ready Manuscripts.");
    await expect(page.getByText("You contribute the original research. We help turn it into a submission-ready manuscript.")).toBeVisible();
    await expect(page.getByTestId("responsibility-message")).toHaveText(RESPONSIBILITY);

    await registerAndOnboard(page);
    await page.goto("/projects/new");
    await expect(page.getByTestId("responsibility-message")).toHaveText(RESPONSIBILITY);
    // Creating a project is impossible without acknowledging it.
    await field(page, "Project title").fill("Message check project");
    await expect(page.getByRole("button", { name: "Create project" })).toBeDisabled();
    await createProject(page, "Message check project");
});
