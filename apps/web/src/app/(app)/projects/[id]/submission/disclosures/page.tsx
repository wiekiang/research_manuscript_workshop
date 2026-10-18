"use client";

import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { SourceQuote } from "@/components/research/provenance-link";
import { DisclosuresForm } from "@/components/submission/disclosures-form";
import { SubmissionNav } from "@/components/submission/submission-nav";
import { useResource } from "@/hooks/use-resource";
import type { DisclosuresView } from "@/lib/api/types";

export default function DisclosuresPage() {
    const { project } = useProject();
    const pid = project?.id ?? "";
    const view = useResource<DisclosuresView>(pid ? `/v1/projects/${pid}/disclosures` : null);
    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    return (
        <div className="flex flex-col gap-8">
            <SubmissionNav projectId={pid} />
            <Section title="Disclosures and AI-use policy" description={view.data ? <span data-testid="disclosure-guidance">{view.data.guidance}</span> : undefined}>
                {view.isLoading && !view.data && <Loading label="Loading disclosures" />}
                <ErrorAlert error={view.error} />
                {view.data && (
                    <div className="flex flex-col gap-6">
                        <div className="flex flex-col gap-2">
                            <h3 className="text-sm font-semibold text-primary">Venue AI policy found in the confirmed CFP</h3>
                            {view.data.venue_ai_policy_from_cfp?.quote ? (
                                <SourceQuote quote={view.data.venue_ai_policy_from_cfp.quote} />
                            ) : (
                                <p data-testid="no-venue-policy" className="text-sm text-tertiary">
                                    No AI policy statement was found in a confirmed CFP for this project. Look up the current venue and publisher policy yourself.
                                </p>
                            )}
                        </div>
                        <p className="text-sm text-secondary">
                            {view.data.record_version ? `Recorded version ${view.data.record_version}.` : "Nothing recorded yet."}
                        </p>
                        <DisclosuresForm key={view.data.record_version} view={view.data} projectId={pid} canEdit={canEdit} onSaved={() => void view.reload()} />
                    </div>
                )}
            </Section>
        </div>
    );
}
