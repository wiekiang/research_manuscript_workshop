import { expect, test } from "@playwright/test";
import { createProject, field, registerAndOnboard } from "./helpers";

test("submission preparation: AI author refused verbatim, disclosure validation, honest early states, no submit action", async ({ page }) => {
    await registerAndOnboard(page);
    const id = await createProject(page, "Submission preparation project");

    // Readiness: a new project is a research proposal; the notice says nothing is submitted.
    await page.goto(`/projects/${id}/submission`);
    await expect(page.getByRole("heading", { name: "Submission readiness" })).toBeVisible();
    await expect(page.getByTestId("readiness-current-stage")).toHaveAttribute("data-stage", "research_proposal");
    await expect(page.getByTestId("readiness-notice")).toHaveText("The platform does not submit to any venue. PACKAGE_READY means ready for human export.");
    await expect(page.getByTestId("readiness-stepper").getByRole("listitem")).toHaveCount(7);

    // Authors: the server refuses an AI tool as an author and the problem is shown word for word.
    await page.goto(`/projects/${id}/submission/authors`);
    await expect(page.getByTestId("authors-note")).toHaveText("The contribution log is evidence for author review, never an authorship certification.");
    await expect(page.getByTestId("authors-empty")).toBeVisible();
    await field(page, "Full name (author 1)").fill("ChatGPT");
    await page.getByText("Investigation", { exact: true }).click();
    await field(page, "Contribution statement (author 1)").fill("Drafted parts of the text.");
    await field(page, "Competing interests (author 1)").fill("None declared");
    await field(page, "Funding (author 1)").fill("No external funding");
    await page.getByRole("button", { name: "Save author record" }).click();
    const problems = page.getByTestId("author-problems");
    await expect(problems).toContainText("author 1 (ChatGPT): AI tools cannot be listed as authors; describe AI use in the disclosure");
    await expect(page.getByTestId("author-entry")).toHaveCount(0);

    // A natural person is accepted; assent is never inferred.
    await field(page, "Full name (author 1)").fill("Dr E2E Researcher");
    await page.getByText("This entry describes a natural person", { exact: false }).click();
    await page.getByRole("button", { name: "Save author record" }).click();
    await expect(page.getByTestId("author-entry")).toHaveCount(1);
    await expect(page.getByTestId("author-entry")).toContainText("No approval yet");
    await expect(page.getByText("There is no manuscript version yet, so authors cannot approve a version.")).toBeVisible();

    // Disclosures: client-side validation mirrors the server's minimums; no policy text is invented.
    await page.goto(`/projects/${id}/submission/disclosures`);
    await expect(page.getByTestId("no-venue-policy")).toBeVisible();
    await page.getByRole("button", { name: "Save disclosures" }).click();
    await expect(page.getByTestId("disclosure-problems").getByRole("listitem")).toHaveCount(7);
    await expect(page.getByTestId("disclosure-problems")).toContainText("AI use (in your words): at least 10 characters");

    // Eligibility without an official target needs human resolution, never "eligible".
    await page.goto(`/projects/${id}/submission/eligibility`);
    await page.getByRole("button", { name: "Evaluate eligibility" }).click();
    await expect(page.getByTestId("eligibility-result")).toHaveAttribute("data-status", "needs_human_resolution");
    await expect(page.getByTestId("eligibility-reasons")).toContainText("no recorded deadline governs 'new_submission'; confirm the submission path from the official source");

    // H4 and packages are unavailable until a manuscript exists; the server's reason is shown.
    await page.goto(`/projects/${id}/submission/approval`);
    await expect(page.getByTestId("manifest-unavailable")).toContainText("draft the manuscript first");
    await page.goto(`/projects/${id}/submission/packages`);
    await expect(page.getByTestId("packages-notice")).toHaveText("Exports are for human submission through the venue's own system; nothing is submitted for you.");
    await expect(page.getByTestId("packages-empty")).toBeVisible();
    await page.getByRole("button", { name: "Build export package" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "draft the manuscript first" })).toBeVisible();

    // Nowhere in the workspace is there a submit action.
    for (const p of ["", "/authors", "/disclosures", "/eligibility", "/approval", "/packages"]) {
        await page.goto(`/projects/${id}/submission${p}`);
        await expect(page.getByRole("heading").first()).toBeVisible();
        await expect(page.getByRole("button", { name: /\bsubmit\b/i })).toHaveCount(0);
    }
});
