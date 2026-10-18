import { StatusBadge } from "@/components/research/status-badge";
import { ArtifactLink } from "@/components/research/provenance-link";
import { FixtureNotice } from "@/components/research/verification-method-label";
import type { MetaReview, ReviewReportSummary } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import { FUNCTION_LABEL, FUNCTION_METHOD, FUNCTION_ORDER, SEVERITY_LABEL, SEVERITY_ORDER, reportStatusKey } from "@/lib/review";

/** One card per frozen function report. The status is shown first and "not performed" is never rendered as passed. */
export function ReportCards({ reports, functions }: { reports: ReviewReportSummary[]; functions: string[] }) {
    const order = FUNCTION_ORDER.filter((f) => functions.includes(f));
    return (
        <ul className="grid gap-3 md:grid-cols-2">
            {order.map((fn) => {
                const r = reports.find((x) => x.function === fn);
                return (
                    <li key={fn} data-testid="review-report" data-function={fn} data-status={r?.status ?? "pending"} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-semibold text-primary">{FUNCTION_LABEL[fn] ?? fn}</span>
                            {r ? <StatusBadge status={reportStatusKey(r.status)} /> : <StatusBadge status="running" label="Not frozen yet" />}
                        </div>
                        <p className="text-xs text-tertiary">{FUNCTION_METHOD[fn]}</p>
                        {r?.summary?.reason && <p className="text-sm text-secondary">Not performed: {String(r.summary.reason)}</p>}
                        {r && (
                            <p className="flex flex-wrap items-center gap-3 text-xs text-tertiary">
                                Frozen {formatDateTime(r.frozen_at)}
                                <ArtifactLink artifactId={r.artifact_id} label="Frozen report" />
                            </p>
                        )}
                        {r && fn === "scientific" && r.status !== "not_performed" && <ScientificSummary report={r} />}
                        {r && fn === "technical" && <TechnicalSummary summary={r.summary} />}
                    </li>
                );
            })}
        </ul>
    );
}

const ASSESSMENTS = ["question", "protocol", "evidence", "contribution", "conclusions"] as const;

/** The model-assisted reviewer's assessments, labelled with their provider; fixture replays carry the fixture notice. */
function ScientificSummary({ report }: { report: ReviewReportSummary }) {
    const prov = report.provenance as { provider?: string; model?: string; label?: string };
    return (
        <div className="flex flex-col gap-1" data-testid="scientific-summary">
            <p className="text-xs text-tertiary">
                Model-assisted review{prov.provider ? ` · ${prov.provider}${prov.model ? ` / ${prov.model}` : ""}` : ""}. Advisory; a researcher decides.
            </p>
            <FixtureNotice provider={prov.provider} />
            <dl className="grid gap-1 text-xs sm:grid-cols-[7rem_1fr]">
                {ASSESSMENTS.filter((k) => typeof report.summary[k] === "string").map((k) => (
                    <div key={k} className="contents">
                        <dt className="text-tertiary">{humanize(k)}</dt>
                        <dd className="text-secondary">{String(report.summary[k])}</dd>
                    </div>
                ))}
            </dl>
        </div>
    );
}

function TechnicalSummary({ summary }: { summary: Record<string, unknown> }) {
    const results = (summary.results ?? {}) as Record<string, { assurance?: string; recomputation?: string; detail?: string }>;
    const keys = Object.keys(results);
    if (keys.length === 0) return <p className="text-xs text-tertiary">No committed results.</p>;
    return (
        <ul className="flex flex-col gap-1 text-xs text-secondary" data-testid="technical-results">
            {keys.map((k) => (
                <li key={k} className="flex flex-wrap items-center gap-2">
                    <span className="font-mono">{k}</span>
                    <StatusBadge status={results[k].recomputation === "passed" ? "passed" : results[k].recomputation === "failed" ? "failed" : "not_performed"} label={`Recomputation: ${humanize(results[k].recomputation ?? "not_performed")}`} />
                    <span>Assurance: {humanize(results[k].assurance ?? "unknown")}</span>
                    {results[k].detail && <span className="text-tertiary">{results[k].detail}</span>}
                </li>
            ))}
        </ul>
    );
}

export function MetaReviewPanel({ meta }: { meta: MetaReview | null }) {
    if (!meta) return <p className="text-sm text-tertiary">The meta-review starts only after every function has frozen its own report.</p>;
    return (
        <div data-testid="meta-review" className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
            <p className="text-sm text-secondary">{meta.note}</p>
            <table className="text-left text-sm">
                <caption className="sr-only">Findings by function and severity</caption>
                <thead>
                    <tr className="text-xs text-tertiary">
                        <th scope="col" className="py-1 pr-4 font-medium">Function</th>
                        {SEVERITY_ORDER.map((s) => (
                            <th key={s} scope="col" className="py-1 pr-4 font-medium">{SEVERITY_LABEL[s]}</th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {Object.entries(meta.counts).map(([fn, c]) => (
                        <tr key={fn}>
                            <th scope="row" className="py-1 pr-4 font-normal text-secondary">{FUNCTION_LABEL[fn] ?? fn}</th>
                            {SEVERITY_ORDER.map((s) => (
                                <td key={s} className="py-1 pr-4 text-primary">{c[s] ?? 0}</td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
            {meta.not_performed.length > 0 && (
                <ul className="list-disc pl-5 text-sm text-secondary" data-testid="meta-not-performed">
                    {meta.not_performed.map((n) => (
                        <li key={n.function}>
                            {FUNCTION_LABEL[n.function] ?? n.function} was not performed{n.detail ? `: ${n.detail}` : ""}.
                        </li>
                    ))}
                </ul>
            )}
            <div>
                <h3 className="text-sm font-semibold text-primary">Disagreements between reviewers</h3>
                {meta.disagreements.length === 0 ? (
                    <p className="text-sm text-tertiary">None recorded.</p>
                ) : (
                    <ul className="list-disc pl-5 text-sm text-secondary" data-testid="meta-disagreements">
                        {meta.disagreements.map((d, i) => (
                            <li key={i}>
                                {d.span_id ? `Sentence ${d.span_id}` : `Claim ${d.claim_id}`}: flagged by {d.flagged_by.map((f) => FUNCTION_LABEL[f] ?? f).join(", ")}; judged acceptable by {FUNCTION_LABEL[d.judged_ok_by] ?? d.judged_ok_by}.
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    );
}
