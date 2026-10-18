"use client";

import { useState } from "react";
import { useProject } from "@/components/project/project-context";
import { Section } from "@/components/research/page-header";
import { EligibilityForm, EligibilityResultView } from "@/components/submission/eligibility-panel";
import { SubmissionNav } from "@/components/submission/submission-nav";
import type { EligibilityResult } from "@/lib/api/types";

export default function EligibilityPage() {
    const { project } = useProject();
    const [result, setResult] = useState<EligibilityResult>();
    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    return (
        <div className="flex flex-col gap-8">
            <SubmissionNav projectId={project.id} />
            <Section
                title="Deadline eligibility"
                description="Evaluates the intended next action against only the official deadlines and prerequisites that govern it. Unknown scope or time zone needs your resolution on the CFP page. The assessment is re-evaluated when the project moves to package-ready."
            >
                <EligibilityForm projectId={project.id} canEdit={canEdit} onResult={setResult} />
            </Section>
            {result && (
                <Section title="Assessment">
                    <EligibilityResultView result={result} />
                </Section>
            )}
        </div>
    );
}
