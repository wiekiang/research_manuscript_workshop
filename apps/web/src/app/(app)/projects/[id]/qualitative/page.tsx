"use client";

import { useEffect } from "react";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { QualitativeWorkspace } from "@/components/synthesis/qualitative-workspace";
import { useResource } from "@/hooks/use-resource";
import type { ContributionEntry, QualWorkspace } from "@/lib/api/types";

export default function QualitativePage() {
    const { project, taskTick } = useProject();
    const pid = project?.id ?? "";
    const qual = useResource<QualWorkspace>(pid ? `/v1/projects/${pid}/qual` : null);
    const contributions = useResource<{ items: ContributionEntry[] }>(pid ? `/v1/projects/${pid}/contributions` : null);

    useEffect(() => {
        void Promise.all([qual.reload(), contributions.reload()]);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);

    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Qualitative analysis"
                description={
                    <>
                        Coding with an audit trail under the frozen protocol: every coded segment is checked verbatim against its source, and every theme traces to coded segments. Upload
                        de-identified transcripts and notes on the{" "}
                        <a className="text-brand-secondary underline" href={`/projects/${pid}/contributions`}>
                            Contributions
                        </a>{" "}
                        page. The platform records ethics approval; it does not grant it.
                    </>
                }
            >
                {qual.isLoading && !qual.data && <Loading label="Loading the qualitative workspace" />}
                <ErrorAlert error={qual.error} />
            </Section>
            {qual.data && (
                <QualitativeWorkspace
                    projectId={pid}
                    data={qual.data}
                    sources={contributions.data?.items ?? []}
                    canEdit={canEdit}
                    onChanged={() => void Promise.all([qual.reload(), contributions.reload()])}
                />
            )}
        </div>
    );
}
