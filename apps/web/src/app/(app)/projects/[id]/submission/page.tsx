"use client";

import { useEffect } from "react";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { GatePanel } from "@/components/review/gate-panel";
import { ReadinessPanel } from "@/components/submission/readiness-panel";
import { EXPORT_NOTICE, SubmissionNav } from "@/components/submission/submission-nav";
import { useResource } from "@/hooks/use-resource";
import type { ReadinessView } from "@/lib/api/types";

export default function SubmissionPage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const view = useResource<ReadinessView>(pid ? `/v1/projects/${pid}/readiness` : null);
    useEffect(() => {
        void view.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    const reloadAll = () => void Promise.all([view.reload(), reload()]);
    return (
        <div className="flex flex-col gap-8">
            <SubmissionNav projectId={pid} />
            <Section title="Submission readiness" description={EXPORT_NOTICE}>
                {view.isLoading && !view.data && <Loading label="Loading readiness" />}
                <ErrorAlert error={view.error} />
                {view.data && <ReadinessPanel view={view.data} projectId={pid} canEdit={canEdit} onChanged={reloadAll} />}
            </Section>
            <Section title="Compliance review → final approval" description="Evaluated by the server; the pre-approval readiness assessment is one of these gates.">
                <GatePanel project={project} fromState="COMPLIANCE_REVIEW" toState="FINAL_APPROVAL" gateIds={["compliance.checked", "integrity.checked", "readiness.pre_approval"]} onAdvanced={reloadAll} />
            </Section>
            <Section title="Approved for export → package ready" description="Requires a package verified against the H4 content manifest and current submission eligibility. Package-ready means ready for your own export, not submitted.">
                <GatePanel project={project} fromState="APPROVED_FOR_EXPORT" toState="PACKAGE_READY" gateIds={["package.verified", "eligibility.current", "approvals.h1_to_h4_current"]} onAdvanced={reloadAll} />
            </Section>
        </div>
    );
}
