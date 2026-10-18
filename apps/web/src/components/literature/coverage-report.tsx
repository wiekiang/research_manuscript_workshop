"use client";

import type { ReactNode } from "react";
import { ArtifactLink } from "@/components/research/provenance-link";
import { Section } from "@/components/research/page-header";
import type { CoverageAssessment } from "@/lib/api/types";
import { safeCoverageLevel } from "@/lib/literature";

function Count({ label, value, href }: { label: string; value: number | string; href?: string }) {
    const body: ReactNode = (
        <>
            <span className="text-xl font-semibold text-primary">{value}</span>
            <span className="text-xs text-tertiary">{label}</span>
        </>
    );
    return href ? (
        <a href={href} className="flex flex-col rounded-lg bg-secondary p-3 outline-focus-ring hover:bg-secondary_hover focus-visible:outline-2">
            {body}
        </a>
    ) : (
        <div className="flex flex-col rounded-lg bg-secondary p-3">{body}</div>
    );
}

/** Counts derive only from stored search, screening and evidence records; each links to the records behind it. */
export function CoverageReport({ projectId, cov }: { projectId: string; cov: CoverageAssessment }) {
    const c = cov.counts;
    const papers = (f: string) => `/projects/${projectId}/literature?filter=${f}#papers`;
    const history = `/projects/${projectId}/literature#search-history`;
    return (
        <div className="flex flex-col gap-6">
            <p data-testid="coverage-message" className="rounded-xl bg-warning-primary p-4 text-sm text-secondary">
                {cov.message}
            </p>
            <Section title="Coverage counts" description="Each number is computed from stored records. Select a number to see the records behind it.">
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Count label="Records retrieved across searches" value={c.retrieved_records} href={history} />
                    <Count label="Unique records after deduplication" value={c.unique_records} href={history} />
                    <Count label="Papers in this project" value={c.papers_total} href={papers("")} />
                    <Count label="Added manually or uploaded" value={c.manual_or_uploaded} href={papers("manual")} />
                    <Count label="Full texts reviewed" value={c.fulltext_reviewed} href={papers("fulltext")} />
                    <Count label="Abstract only" value={c.abstract_only} href={papers("abstract")} />
                    <Count label="Metadata only" value={c.metadata_only} href={papers("metadata")} />
                    <Count label="Full text inaccessible or not permitted" value={c.fulltext_inaccessible_or_not_permitted} href={papers("inaccessible")} />
                    <Count label="Screened" value={c.screened} href={papers("screened")} />
                    <Count label="Included" value={c.included} href={papers("included")} />
                    <Count label="Excluded" value={c.excluded} href={papers("excluded")} />
                    <Count label="Papers contributing verified evidence" value={c.papers_contributing_verified_evidence} href={`/projects/${projectId}/evidence`} />
                    <Count label="Identity verified" value={c.identity_verified} href={papers("identity_verified")} />
                    <Count label="Identity problems" value={c.identity_problems} href={papers("identity_problem")} />
                </div>
            </Section>
            <Section title="Coverage level" description="A summary of how much was actually reviewed. It never asserts that the search found all relevant work.">
                <p className="text-sm text-primary">
                    <span className="font-semibold capitalize">{safeCoverageLevel(cov.coverage_level)}</span> — {cov.rationale.replace(/comprehensive/gi, "complete")}
                </p>
                <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                        <h3 className="text-sm font-semibold text-secondary">Sources queried</h3>
                        <p className="text-sm text-tertiary">{c.sources_queried.join(", ") || "None yet"}</p>
                        {c.unavailable_sources.length > 0 && (
                            <>
                                <h3 className="mt-2 text-sm font-semibold text-secondary">Unavailable sources</h3>
                                <ul className="text-sm text-warning-primary">
                                    {c.unavailable_sources.map((s) => (
                                        <li key={s}>{s}</li>
                                    ))}
                                </ul>
                            </>
                        )}
                    </div>
                    <div>
                        <h3 className="text-sm font-semibold text-secondary">Exclusion reasons</h3>
                        <ul className="text-sm text-tertiary">
                            {c.exclusion_reasons.length === 0 ? <li>None recorded</li> : c.exclusion_reasons.map((r) => <li key={r}>{r}</li>)}
                        </ul>
                    </div>
                </div>
                <div>
                    <h3 className="text-sm font-semibold text-secondary">Limitations</h3>
                    <ul className="list-disc pl-5 text-sm text-tertiary">
                        {cov.limitations.map((l) => (
                            <li key={l}>{l}</li>
                        ))}
                    </ul>
                </div>
                <div>
                    <h3 className="text-sm font-semibold text-secondary">Queries</h3>
                    <ul className="text-sm text-tertiary">
                        {c.queries.length === 0 ? (
                            <li>No completed searches</li>
                        ) : (
                            c.queries.map((q, i) => (
                                <li key={i}>
                                    “{q.query}” — {q.executed_at ?? "not executed"}
                                </li>
                            ))
                        )}
                    </ul>
                </div>
                <p className="text-xs text-tertiary">
                    Assessment version {cov.version}. <ArtifactLink artifactId={cov.artifact_id} label="Coverage assessment artifact" />
                </p>
            </Section>
        </div>
    );
}
