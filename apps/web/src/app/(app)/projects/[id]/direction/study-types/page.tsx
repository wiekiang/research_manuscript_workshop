"use client";

import { studyTypeTitle } from "@/components/opportunities/opportunity-card";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import type { StudyTypeTaxonomy } from "@/lib/api/types";

export default function StudyTypesPage() {
    const { project } = useProject();
    const pid = project?.id ?? "";
    const tax = useResource<StudyTypeTaxonomy>(pid ? `/v1/projects/${pid}/study-types` : null);
    if (!project) return null;
    return (
        <div className="flex flex-col gap-10">
            <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/direction`}>
                Back to research direction
            </a>
            {tax.isLoading && !tax.data && <Loading label="Loading taxonomy" />}
            <ErrorAlert error={tax.error} />
            {tax.data && (
                <>
                    <Section title="Study types" description={tax.data.note}>
                        <ul className="flex flex-col gap-3">
                            {tax.data.taxonomy.map((t) => (
                                <li key={t.study_type} data-testid="taxonomy-entry" className="flex flex-col gap-1 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <span className="font-medium text-primary">{t.title || studyTypeTitle(t.study_type)}</span>
                                        <StatusBadge status={t.enabled_for_submission_ready ? "complete" : "not_performed"} label={t.enabled_for_submission_ready ? "Enabled" : "Planning only"} />
                                        <span className="text-xs text-tertiary">definition v{t.definition_version}</span>
                                    </div>
                                    <p className="text-sm text-secondary">{t.definition}</p>
                                    <p className="text-xs text-tertiary">{t.availability}</p>
                                    {t.planning_only_reason && <p className="text-xs text-warning-primary">Planning only: {t.planning_only_reason}</p>}
                                    {t.reporting_standard && <p className="text-xs text-tertiary">Reporting standard: {t.reporting_standard}</p>}
                                </li>
                            ))}
                        </ul>
                    </Section>
                    <Section title="Venue submission categories" description="What kind of submission the venue accepts. Independent of the study type.">
                        <dl className="grid gap-3 sm:grid-cols-2">
                            {Object.entries(tax.data.venue_categories).map(([k, v]) => (
                                <div key={k} className="rounded-lg bg-secondary p-3">
                                    <dt className="text-sm font-medium text-primary">{k.replace(/_/g, " ")}</dt>
                                    <dd className="text-sm text-tertiary">{v}</dd>
                                </div>
                            ))}
                        </dl>
                    </Section>
                </>
            )}
        </div>
    );
}
