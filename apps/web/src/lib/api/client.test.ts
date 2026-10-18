import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiPath, request } from "./client";

describe("apiPath (acceptance #33: exactly one /v1 prefix)", () => {
    it("accepts canonical paths", () => {
        expect(apiPath("/v1/projects")).toBe("/v1/projects");
        expect(apiPath("/v1/projects/abc/cfp/resolve")).toBe("/v1/projects/abc/cfp/resolve");
    });
    it.each(["/projects", "v1/projects", "/v2/projects", "/api/v1/projects"])("rejects a missing prefix: %s", (p) => {
        expect(() => apiPath(p)).toThrow(/must start with \/v1\//);
    });
    it.each(["/v1/v1/projects", "/v1/projects/v1/x"])("rejects a doubled prefix: %s", (p) => {
        expect(() => apiPath(p)).toThrow(/doubled/);
    });
    it("rejects absolute and non-normalized paths", () => {
        expect(() => apiPath("/v1//projects")).toThrow();
        expect(() => apiPath("http://evil.example/v1/x")).toThrow();
    });
});

describe("request", () => {
    afterEach(() => vi.restoreAllMocks());

    it("sends the CSRF header on unsafe methods and parses the stable error shape", async () => {
        document.cookie = "rp_csrf=token-123";
        const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
            new Response(JSON.stringify({ error: { code: "gate_unsatisfied", message: "resolve these", details: { reasons: ["x"] }, request_id: "rid1" } }), {
                status: 422,
                headers: { "content-type": "application/json" },
            }),
        );
        const err = await request("/v1/projects/p/cfp/confirm", { method: "POST", body: { a: 1 }, idempotencyKey: "k1" }).catch((e) => e);
        expect(err).toBeInstanceOf(ApiError);
        expect(err).toMatchObject({ status: 422, code: "gate_unsatisfied", requestId: "rid1" });
        const init = fetchMock.mock.calls[0][1] as RequestInit;
        const headers = init.headers as Record<string, string>;
        expect(headers["x-csrf-token"]).toBe("token-123");
        expect(headers["Idempotency-Key"]).toBe("k1");
        expect(init.credentials).toBe("include");
    });

    it("refreshes the session once on 401 and retries", async () => {
        const fetchMock = vi
            .spyOn(globalThis, "fetch")
            .mockResolvedValueOnce(new Response("{}", { status: 401, headers: { "content-type": "application/json" } }))
            .mockResolvedValueOnce(new Response("{}", { status: 200, headers: { "content-type": "application/json" } }))
            .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }));
        const res = await request<{ ok: boolean }>("/v1/projects");
        expect(res.ok).toBe(true);
        expect(fetchMock.mock.calls.map((c) => c[0])).toEqual(["/v1/projects", "/v1/auth/refresh", "/v1/projects"]);
    });
});
