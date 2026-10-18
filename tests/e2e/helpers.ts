import { type Locator, type Page, expect } from "@playwright/test";

export const PASSWORD = "Correct-Horse-9-Battery";
export const RESPONSIBILITY =
    "Our platform helps with discovery, evidence review, research planning, manuscript development, and conference checks. You are responsible for the originality, validity, and integrity of your contribution.";

function escapeRe(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** A text field by its visible label (the required marker " *" is part of the accessible name). */
export function field(page: Page | Locator, label: string) {
    return page.getByRole("textbox", { name: new RegExp(`^${escapeRe(label)}( \\*)?$`) });
}

export function uniqueEmail(prefix = "e2e"): string {
    return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.org`;
}

/** Register a new account through the UI and acknowledge the responsibility message on onboarding. */
export async function registerAndOnboard(page: Page, email = uniqueEmail()): Promise<string> {
    await page.goto("/register");
    await field(page, "Your name").fill("Dr E2E Researcher");
    await field(page, "Email").fill(email);
    await field(page, "Password").fill(PASSWORD);
    await field(page, "Workspace name").fill("E2E Lab");
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/onboarding/);
    await expect(page.getByTestId("responsibility-message")).toHaveText(RESPONSIBILITY);
    await page.getByText("I understand and accept this responsibility").click();
    await page.getByRole("button", { name: "Acknowledge and continue" }).click();
    await expect(page.getByText("Acknowledged.")).toBeVisible();
    await page.getByRole("link", { name: "Go to the dashboard" }).click();
    await expect(page.getByRole("heading", { name: "Your research projects" })).toBeVisible();
    return email;
}

export async function createProject(page: Page, title: string): Promise<string> {
    await page.goto("/projects/new");
    await expect(page.getByTestId("responsibility-message")).toHaveText(RESPONSIBILITY);
    await field(page, "Project title").fill(title);
    await page.getByText("I have read this and accept responsibility for my contribution").click();
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+\/cfp/);
    return page.url().match(/projects\/([0-9a-f-]+)/)![1];
}
