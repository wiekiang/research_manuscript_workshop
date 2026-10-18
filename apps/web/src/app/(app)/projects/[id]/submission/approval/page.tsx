"use client";

import { useState } from "react";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Field, Loading, Section } from "@/components/research/page-header";
import { GatePanel } from "@/components/review/gate-panel";
import { FinalApprovalForm, ManifestItems } from "@/components/submission/content-manifest";
import { SubmissionNav } from "@/components/submission/submission-nav";
import { useResource } from "@/hooks/use-resource";
import { ApiError } from "@/lib/api/client";
import type { ContentManifestView, FinalApprovalResult } from "@/lib/api/types";
import { STATE_LABEL } from "@/lib/states";

export default function ApprovalPage() {
    const { project, reload } = useProject();
    const pid = project?.id ?? "";
    const canEdit = project?.my_role === "owner" || project?.my_role === "coauthor";
    const view = useResource<ContentManifestView>(pid && canEdit ? `/v1/projects/${pid}/content-manifest` : null);
    const [signed, setSigned] = useState<FinalApprovalResult>();
    if (!project) return null;
    return (
        <div className="flex flex-col gap-8">
            <SubmissionNav projectId={pid} />
            <Section
                title="Frozen content manifest"
                description="Everything H4 signs: the exact committed artifacts. Any later change to these items, the author record or the disclosures invalidates H4 and the packages built from it."
            >
                {!canEdit && <p className="text-sm text-tertiary">Only owners and co-authors can view the content manifest.</p>}
                {view.isLoading && !view.data && <Loading label="Loading content manifest" />}
                {view.error instanceof ApiError && view.error.status === 422 ? (
                    <p data-testid="manifest-unavailable" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        The content manifest is not available yet: {view.error.message}
                    </p>
                ) : (
                    <ErrorAlert error={view.error} title="The content manifest is not available yet" />
                )}
                {view.data && (
                    <div className="flex flex-col gap-4">
                        <p className="text-sm text-secondary">Manuscript version {view.data.manuscript_version}</p>
                        <ManifestItems view={view.data} />
                        {view.data.problems.length > 0 && (
                            <div data-testid="manifest-problems" className="flex flex-col gap-1">
                                <p className="text-sm font-semibold text-primary">Missing before H4</p>
                                <ul className="list-disc pl-5 text-sm text-secondary">
                                    {view.data.problems.map((p) => (
                                        <li key={p}>{p}</li>
                                    ))}
                                </ul>
                            </div>
                        )}
                        {view.data.authors_without_approval.length > 0 && (
                            <div data-testid="authors-without-approval" className="flex flex-col gap-1">
                                <p className="text-sm font-semibold text-primary">Authors who have not approved this version</p>
                                <ul className="list-disc pl-5 text-sm text-secondary">
                                    {view.data.authors_without_approval.map((a) => (
                                        <li key={a}>{a}</li>
                                    ))}
                                </ul>
                            </div>
                        )}
                    </div>
                )}
            </Section>
            {view.data && !signed && (
                <Section title="Final approval (H4)">
                    <FinalApprovalForm
                        view={view.data}
                        projectId={pid}
                        inFinalApproval={project.state === "FINAL_APPROVAL"}
                        onSigned={(r) => {
                            setSigned(r);
                            void reload();
                        }}
                    />
                </Section>
            )}
            {signed && (
                <Section title="H4 recorded">
                    <dl data-testid="h4-result" className="grid gap-3 sm:grid-cols-2">
                        <Field label="Content manifest hash">
                            <span className="font-mono text-xs break-all">{signed.content_manifest_hash}</span>
                        </Field>
                        <Field label="Project state">{STATE_LABEL[signed.transition.state as keyof typeof STATE_LABEL] ?? signed.transition.state}</Field>
                    </dl>
                </Section>
            )}
            <Section title="Final approval → approved for export" description="Evaluated by the server.">
                <GatePanel
                    project={project}
                    fromState="FINAL_APPROVAL"
                    toState="APPROVED_FOR_EXPORT"
                    gateIds={["h4.approved", "approvals.h1_to_h4_current", "method.enabled_for_submission", "contribution.recorded", "blockers.none"]}
                    onAdvanced={() => void reload()}
                />
            </Section>
        </div>
    );
}
