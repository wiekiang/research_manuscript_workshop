"use client";

import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { AuthorRoster } from "@/components/submission/author-assent";
import { AuthorsEditor } from "@/components/submission/authors-editor";
import { SubmissionNav } from "@/components/submission/submission-nav";
import { useResource } from "@/hooks/use-resource";
import type { AuthorsView, Member } from "@/lib/api/types";
import { useSession } from "@/providers/session";

export default function AuthorsPage() {
    const { project } = useProject();
    const { me } = useSession();
    const pid = project?.id ?? "";
    const view = useResource<AuthorsView>(pid ? `/v1/projects/${pid}/authors` : null);
    const members = useResource<Member[]>(pid ? `/v1/projects/${pid}/members` : null);
    if (!project) return null;
    const myId = me?.user.id;
    const iAmCorresponding = !!members.data?.find((m) => m.user_id === myId)?.is_corresponding_author;
    const reloadAll = () => void Promise.all([view.reload(), members.reload()]);
    return (
        <div className="flex flex-col gap-8">
            <SubmissionNav projectId={pid} />
            <Section
                title="Authors"
                description={view.data ? <span data-testid="authors-note">{view.data.note}</span> : "Author identities, order, contributions and declarations."}
            >
                {view.isLoading && !view.data && <Loading label="Loading authors" />}
                <ErrorAlert error={view.error} />
                {view.data && (
                    <AuthorRoster view={view.data} projectId={pid} myUserId={myId} iAmCorresponding={iAmCorresponding} onChanged={reloadAll} />
                )}
            </Section>
            {view.data && (
                <Section
                    title={view.data.record_version ? `Edit author record (version ${view.data.record_version})` : "Create the author record"}
                    description="Saving a new version invalidates any final approval (H4) and package that bound the previous author record."
                >
                    <AuthorsEditor key={view.data.record_version} view={view.data} members={members.data ?? []} projectId={pid} canSave={project.my_role === "owner"} onSaved={reloadAll} />
                </Section>
            )}
        </div>
    );
}
