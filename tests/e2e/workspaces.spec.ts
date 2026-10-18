import { expect, test } from "@playwright/test";
import { createProject, registerAndOnboard } from "./helpers";

const AVAILABLE = [
    { path: "", heading: "What is needed next" },
    { path: "/activity", heading: "Agent and workflow tasks" },
    { path: "/contributions", heading: "Contribution ledger" },
    { path: "/costs", heading: "Budget" },
    { path: "/settings", heading: "Members and roles" },
    { path: "/discovery", heading: "Ranked candidates" },
    { path: "/templates", heading: "Template register" },
    { path: "/literature", heading: "Search history" },
    { path: "/literature/coverage", heading: "Literature coverage" },
    { path: "/evidence", heading: "Claim registry" },
    { path: "/direction", heading: "Research direction proposals" },
    { path: "/direction/study-types", heading: "Study types" },
    { path: "/methodology", heading: "Method workflow" },
    { path: "/contributions/outcomes", heading: "Contribution validation matrix" },
    { path: "/manuscript", heading: "Manuscript completion" },
    { path: "/review", heading: "Independent review" },
    { path: "/integrity", heading: "Research integrity" },
    { path: "/submission", heading: "Submission readiness" },
    { path: "/submission/authors", heading: "Authors" },
    { path: "/submission/disclosures", heading: "Disclosures and AI-use policy" },
    { path: "/submission/eligibility", heading: "Deadline eligibility" },
    { path: "/submission/approval", heading: "Frozen content manifest" },
    { path: "/submission/packages", heading: "Export packages" },
    { path: "/experiments", heading: "Experiments" },
];
const UNAVAILABLE: string[] = [];

test("every workspace renders real data or an explicit not-available state", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("pageerror", (e) => consoleErrors.push(e.message));
    await registerAndOnboard(page);
    const id = await createProject(page, "Workspace smoke project");

    for (const w of AVAILABLE) {
        await page.goto(`/projects/${id}${w.path}`);
        await expect(page.getByRole("heading", { name: w.heading })).toBeVisible();
        // Next's route announcer is an empty alert region; any ErrorAlert has text.
        await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);
    }
    for (const p of UNAVAILABLE) {
        await page.goto(`/projects/${id}${p}`);
        await expect(page.getByText(/Not available in this release\. Planned for milestone/)).toBeVisible();
    }
    for (const [p, h] of [
        ["/dashboard", "Your research projects"],
        ["/conferences", "Conferences"],
        ["/conferences/registry", "Official-source registry"],
        ["/notifications", "Notifications"],
        ["/settings", "Settings"],
    ]) {
        await page.goto(p);
        await expect(page.getByRole("heading", { name: h, level: 1 })).toBeVisible();
    }
    // The blocked Elicit integration is never offered.
    await expect(page.getByText("Elicit")).toHaveCount(0);
    // The dashboard explains what is automated, manual or unavailable.
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "What runs in this release" })).toBeVisible();
    expect(consoleErrors).toEqual([]);
});
