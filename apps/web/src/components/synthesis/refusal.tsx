import { ApiError } from "@/lib/api/client";
import { synthesisHint } from "@/lib/synthesis";
import { cx } from "@/utils/cx";

/** Lists a refusal's problem details verbatim (problems, validation errors, allowed values). */
export function refusalDetails(err: unknown): string[] {
    if (!(err instanceof ApiError) || !err.details || typeof err.details !== "object") return [];
    const d = err.details as { problems?: unknown; errors?: unknown; allowed?: unknown };
    if (Array.isArray(d.problems)) return d.problems.map(String);
    if (Array.isArray(d.errors)) return (d.errors as { msg?: string; loc?: unknown[] }[]).map((x) => `${(x.loc ?? []).join(".")}: ${x.msg ?? ""}`);
    if (Array.isArray(d.allowed)) return [`Allowed reasons: ${d.allowed.map(String).join("; ")}`];
    return [];
}

/**
 * A server refusal shown word for word with its code, any listed problems and a short hint. `tone="notice"` is used
 * for "not set up yet" states (neutral status, not an error alert).
 */
export function Refusal({ error, tone = "error", className }: { error: unknown; tone?: "error" | "notice"; className?: string }) {
    if (!error) return null;
    const msg = error instanceof Error ? error.message : "Something went wrong";
    const code = error instanceof ApiError ? error.code : undefined;
    const details = refusalDetails(error);
    const hint = synthesisHint(error);
    return (
        <div
            role={tone === "error" ? "alert" : "status"}
            data-testid={tone === "error" ? "synthesis-refusal" : "synthesis-notice"}
            data-code={code}
            className={cx(
                "flex flex-col gap-1 rounded-xl p-4 text-sm",
                tone === "error" ? "border border-error_subtle bg-error-primary" : "bg-secondary ring-1 ring-secondary",
                className,
            )}
        >
            <p className={cx("font-semibold", tone === "error" ? "text-error-primary" : "text-primary")}>{msg}</p>
            {details.length > 0 && (
                <ul className="list-disc pl-5 text-secondary">
                    {details.map((d) => (
                        <li key={d}>{d}</li>
                    ))}
                </ul>
            )}
            {hint && <p className="text-tertiary">{hint}</p>}
            {code && <p className="text-xs text-tertiary">Code {code}</p>}
        </div>
    );
}
