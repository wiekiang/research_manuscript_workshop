"use client";

import { OutcomeReview } from "@/components/method/outcome-review";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import type { ApprovalsView, MatrixView } from "@/lib/api/types";

export default function OutcomesPage() {
    const { project, reload } = useProject();
    const pid = project?.id ?? "";
    const matrix = useResource<MatrixView>(pid ? `/v1/projects/${pid}/contribution-matrix` : null);
    const approvals = useResource<ApprovalsView>(pid ? `/v1/projects/${pid}/approvals` : null);
    if (!project) return null;
    return (
        <div className="flex flex-col gap-6">
            <a className="text-sm text-brand-secondary underline-offset-2 hover:underline" href={`/projects/${pid}/contributions`}>
                Back to the contribution workspace
            </a>
            <h2 className="sr-only">Outcome review</h2>
            {matrix.isLoading && !matrix.data && <Loading label="Loading the contribution matrix" />}
            <ErrorAlert error={matrix.error} />
            <OutcomeReview
                projectId={pid}
                matrix={matrix.data}
                isOwner={project.my_role === "owner"}
                projectState={project.state}
                h3Declaration={approvals.data?.declarations.H3?.text}
                onChanged={() => void Promise.all([matrix.reload(), approvals.reload(), reload()])}
            />
        </div>
    );
}
