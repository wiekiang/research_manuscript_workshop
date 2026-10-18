import { AlertCircle } from "@untitledui/icons";
import { describeError } from "@/lib/api/client";
import { cx } from "@/utils/cx";

interface Props {
    error: unknown;
    title?: string;
    className?: string;
}

/** Explains what failed and shows the stable error code and request ID for support. */
export function ErrorAlert({ error, title, className }: Props) {
    if (!error) return null;
    const d = describeError(error);
    const reasons = extractReasons(d.details);
    return (
        <div role="alert" className={cx("flex gap-3 rounded-xl border border-error_subtle bg-error-primary p-4", className)}>
            <AlertCircle className="mt-0.5 size-5 shrink-0 text-fg-error-primary" aria-hidden="true" />
            <div className="flex min-w-0 flex-col gap-1">
                <p className="text-sm font-semibold text-error-primary">{title ?? d.title}</p>
                {title && <p className="text-sm text-secondary">{d.title}</p>}
                {reasons.length > 0 && (
                    <ul className="list-disc pl-5 text-sm text-secondary">
                        {reasons.map((r) => (
                            <li key={r}>{r}</li>
                        ))}
                    </ul>
                )}
                {(d.code || d.requestId) && (
                    <p className="text-xs text-tertiary">
                        {d.code && <>Error code {d.code}</>}
                        {d.code && d.requestId && ". "}
                        {d.requestId && <>Request ID {d.requestId}</>}
                    </p>
                )}
            </div>
        </div>
    );
}

function extractReasons(details: unknown): string[] {
    if (!details || typeof details !== "object") return [];
    const d = details as { reasons?: unknown; gates?: { passed: boolean; reasons: string[] }[]; problems?: unknown };
    if (Array.isArray(d.reasons)) return d.reasons.map(String);
    if (Array.isArray(d.gates)) return d.gates.filter((g) => !g.passed).flatMap((g) => g.reasons);
    if (Array.isArray(details)) return (details as { msg?: string; loc?: unknown[] }[]).map((x) => `${(x.loc ?? []).join(".")}: ${x.msg ?? ""}`);
    return [];
}
