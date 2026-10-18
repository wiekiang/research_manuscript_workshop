/**
 * Browser API client.
 *
 * - Every path must carry exactly one `/v1` prefix (spec §6, acceptance #33); `apiPath` enforces it.
 * - Session cookies are httpOnly and same-origin (Next rewrites proxy /v1 to the API), so requests use
 *   `credentials: "include"` and send the double-submit CSRF token on unsafe methods.
 * - A 401 triggers one POST /v1/auth/refresh and a single retry.
 * - Errors surface the API's stable shape: { code, message, details, request_id }.
 */

export const API_PREFIX = "/v1";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
    status: number;
    code: string;
    details: unknown;
    requestId: string | null;

    constructor(status: number, code: string, message: string, details: unknown, requestId: string | null) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.code = code;
        this.details = details;
        this.requestId = requestId;
    }
}

/** Validate a client route: exactly one leading `/v1/` segment, no doubled prefix, no absolute URLs. */
export function apiPath(path: string): string {
    if (!path.startsWith(`${API_PREFIX}/`)) {
        throw new Error(`API path must start with ${API_PREFIX}/: ${path}`);
    }
    if (path.slice(API_PREFIX.length).startsWith(`${API_PREFIX}/`) || /\/v1\/(.*\/)?v1\//.test(path)) {
        throw new Error(`API path has a doubled ${API_PREFIX} prefix: ${path}`);
    }
    if (/^[a-z]+:\/\//i.test(path) || path.includes("//")) {
        throw new Error(`API path must be relative and normalized: ${path}`);
    }
    return path;
}

export function readCookie(name: string): string | null {
    if (typeof document === "undefined") return null;
    const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
    return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

export function newIdempotencyKey(scope: string): string {
    const rand = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    return `${scope}:${rand}`;
}

type Body = object | FormData | undefined;

export interface RequestOptions {
    method?: string;
    body?: Body;
    idempotencyKey?: string;
    signal?: AbortSignal;
    /** internal: prevents refresh loops */
    _retried?: boolean;
}

let refreshing: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
    if (!refreshing) {
        refreshing = fetch(apiPath("/v1/auth/refresh"), {
            method: "POST",
            credentials: "include",
            headers: { "x-csrf-token": readCookie("rp_csrf") ?? "" },
        })
            .then((r) => r.ok)
            .catch(() => false)
            .finally(() => {
                setTimeout(() => (refreshing = null), 0);
            });
    }
    return refreshing;
}

async function parseError(res: Response): Promise<ApiError> {
    let payload: { error?: { code?: string; message?: string; details?: unknown; request_id?: string } } = {};
    try {
        payload = await res.json();
    } catch {
        /* non-JSON error body */
    }
    const e = payload.error ?? {};
    return new ApiError(
        res.status,
        e.code ?? `http_${res.status}`,
        e.message ?? res.statusText ?? "Request failed",
        e.details ?? null,
        e.request_id ?? res.headers.get("x-request-id"),
    );
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const method = (opts.method ?? (opts.body ? "POST" : "GET")).toUpperCase();
    const headers: Record<string, string> = { Accept: "application/json" };
    let body: BodyInit | undefined;
    if (opts.body instanceof FormData) {
        body = opts.body;
    } else if (opts.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(opts.body);
    }
    if (UNSAFE.has(method)) {
        const csrf = readCookie("rp_csrf");
        if (csrf) headers["x-csrf-token"] = csrf;
    }
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

    const res = await fetch(apiPath(path), { method, headers, body, credentials: "include", signal: opts.signal });
    if (res.status === 401 && !opts._retried && !path.startsWith("/v1/auth/login") && !path.startsWith("/v1/auth/refresh")) {
        if (await refreshSession()) {
            return request<T>(path, { ...opts, _retried: true });
        }
    }
    if (!res.ok) throw await parseError(res);
    if (res.status === 204) return undefined as T;
    const ct = res.headers.get("content-type") ?? "";
    return (ct.includes("application/json") ? await res.json() : await res.text()) as T;
}

export const api = {
    get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: "GET", signal }),
    post: <T>(path: string, body?: Body, idempotencyKey?: string) => request<T>(path, { method: "POST", body: body ?? {}, idempotencyKey }),
    patch: <T>(path: string, body?: Body) => request<T>(path, { method: "PATCH", body: body ?? {} }),
    put: <T>(path: string, body?: Body) => request<T>(path, { method: "PUT", body: body ?? {} }),
    del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

/** Human-readable message for an unknown error, keeping the error code and request ID visible. */
export function describeError(err: unknown): { title: string; code?: string; requestId?: string | null; details?: unknown } {
    if (err instanceof ApiError) return { title: err.message, code: err.code, requestId: err.requestId, details: err.details };
    if (err instanceof Error) return { title: err.message };
    return { title: "Something went wrong" };
}
