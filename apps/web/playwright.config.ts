import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the running stack (scripts/dev.sh up) and the web dev server.
 * WEB_BASE_URL defaults to the dev server port used by `npm run dev` (3100).
 */
const baseURL = process.env.WEB_BASE_URL ?? "http://localhost:3100";

export default defineConfig({
    testDir: "../../tests/e2e",
    timeout: 120_000,
    expect: { timeout: 15_000 },
    fullyParallel: false,
    retries: 0,
    reporter: [["list"]],
    use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure" },
    projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
    webServer: process.env.WEB_BASE_URL
        ? undefined
        : { command: "npm run dev", url: baseURL, reuseExistingServer: true, timeout: 120_000 },
});
