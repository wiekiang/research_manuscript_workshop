import { CpuChip01, Lock01, User01 } from "@untitledui/icons";
import { StatusBadge } from "@/components/research/status-badge";
import type { ContentSpan, SpanIssue, SpanRecord } from "@/lib/api/types";
import { SPAN_KIND_LABEL, issueTone, originLabel, severityLabel, sortIssues, spanStatusKey } from "@/lib/manuscript";
import { cx } from "@/utils/cx";

const TONE_CLASS = {
    error: "border-error_subtle bg-error-primary text-error-primary",
    warning: "border-utility-amber-300 bg-warning-primary text-warning-primary",
    gray: "border-secondary bg-secondary text-secondary",
};

export function OriginLabel({ origin }: { origin: string }) {
    const o = originLabel(origin);
    const Icon = origin === "human" ? User01 : CpuChip01;
    return (
        <span data-testid="span-origin" data-origin={origin} title={o.description} className="inline-flex items-center gap-1 text-xs text-tertiary">
            <Icon className="size-3.5" aria-hidden="true" />
            {o.label}
        </span>
    );
}

export function IssueList({ issues }: { issues: SpanIssue[] }) {
    if (issues.length === 0) return null;
    return (
        <ul className="flex flex-col gap-1" aria-label="Span check issues">
            {sortIssues(issues).map((i, idx) => (
                <li key={`${i.code}-${idx}`} data-testid="span-issue" data-severity={i.severity} data-code={i.code} className={cx("rounded-md border px-2 py-1 text-xs", TONE_CLASS[issueTone(i.severity)])}>
                    <span className="font-semibold">{severityLabel(i.severity)}</span>
                    <span className="sr-only"> issue</span>: {i.message} <span className="opacity-75">({i.code})</span>
                </li>
            ))}
        </ul>
    );
}

/**
 * One sentence-level span with its provenance: kind, AI vs human origin, protection, the claim/result IDs it cites
 * and the deterministic check results. The text is shown exactly as committed.
 */
export function SpanView({ span, record, projectId }: { span: ContentSpan; record?: SpanRecord; projectId: string }) {
    const issues = record?.issues ?? [];
    const blocker = issues.some((i) => i.severity === "blocker");
    return (
        <div
            id={`span-${span.span_id}`}
            data-testid="manuscript-span"
            data-kind={span.kind}
            data-origin={span.origin}
            data-status={record?.status ?? "ok"}
            className={cx(
                "flex flex-col gap-1.5 rounded-lg p-2 ring-1 ring-inset",
                blocker ? "ring-error_subtle" : issues.length ? "ring-utility-amber-300" : "ring-secondary",
                span.origin === "human" && "bg-secondary_subtle",
            )}
        >
            <p className="text-md text-primary">{span.text}</p>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="text-xs font-medium text-secondary">{SPAN_KIND_LABEL[span.kind] ?? span.kind}</span>
                <OriginLabel origin={span.origin} />
                {span.protected && (
                    <span className="inline-flex items-center gap-1 text-xs text-tertiary" title="Kept when sections are regenerated">
                        <Lock01 className="size-3.5" aria-hidden="true" />
                        Protected
                    </span>
                )}
                {span.claim_ids.map((c) => (
                    <a key={c} href={`/projects/${projectId}/evidence`} className="font-mono text-xs text-brand-secondary underline-offset-2 hover:underline" title="Cited claim">
                        {c}
                    </a>
                ))}
                {span.result_keys.map((r) => (
                    <a key={r} href={`/projects/${projectId}/contributions`} className="font-mono text-xs text-brand-secondary underline-offset-2 hover:underline" title="Cited committed result">
                        {r}
                    </a>
                ))}
                {record && <StatusBadge status={spanStatusKey(record)} />}
            </div>
            <IssueList issues={issues} />
        </div>
    );
}
