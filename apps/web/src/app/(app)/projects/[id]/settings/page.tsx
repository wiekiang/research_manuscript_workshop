"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { ApprovalRecord, Member } from "@/lib/api/types";
import { formatDateTime, shortHash } from "@/lib/format";

export default function ProjectSettings() {
    const { project } = useProject();
    const members = useResource<Member[]>(project ? `/v1/projects/${project.id}/members` : null);
    const approvals = useResource<{ items: ApprovalRecord[] }>(project ? `/v1/projects/${project.id}/approvals` : null);
    const [email, setEmail] = useState("");
    const [role, setRole] = useState("coauthor");
    const [corresponding, setCorresponding] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    if (!project) return null;
    const isOwner = project.my_role === "owner";

    const run = async (fn: () => Promise<unknown>) => {
        setBusy(true);
        setError(undefined);
        try {
            await fn();
            await members.reload();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-10">
            <Section title="Members and roles" description="Owners make scientific decisions and sign H1–H3. Coauthors edit and sign their own contributions. Reviewers comment without approval rights. The corresponding author signs H4.">
                {members.isLoading && <Loading label="Loading members" />}
                <ul className="flex flex-col divide-y divide-secondary rounded-2xl bg-primary ring-1 ring-secondary">
                    {members.data?.map((m) => (
                        <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                            <div>
                                <p className="text-sm font-semibold text-primary">{m.display_name}</p>
                                <p className="text-xs text-tertiary">{m.email}</p>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm text-secondary">{m.role}</span>
                                {m.is_corresponding_author ? (
                                    <StatusBadge status="confirmed" label="Corresponding author" />
                                ) : (
                                    isOwner && (
                                        <Button size="sm" color="secondary" isDisabled={busy} onClick={() => run(() => api.patch(`/v1/projects/${project.id}/members/${m.user_id}`, { is_corresponding_author: true }))}>
                                            Make corresponding author
                                        </Button>
                                    )
                                )}
                            </div>
                        </li>
                    ))}
                </ul>
                {isOwner && (
                    <form
                        className="flex flex-col gap-3 rounded-2xl bg-primary p-5 ring-1 ring-secondary sm:flex-row sm:items-end"
                        onSubmit={(e) => {
                            e.preventDefault();
                            void run(async () => {
                                await api.post(`/v1/projects/${project.id}/members`, { email, role, is_corresponding_author: corresponding });
                                setEmail("");
                            });
                        }}
                    >
                        <Input label="Add a workspace member by email" type="email" value={email} onChange={setEmail} className="flex-1" />
                        <NativeSelect
                            label="Role"
                            value={role}
                            onChange={(e) => setRole(e.target.value)}
                            options={[
                                { label: "Coauthor", value: "coauthor" },
                                { label: "Reviewer", value: "reviewer" },
                                { label: "Owner", value: "owner" },
                            ]}
                            className="sm:w-40"
                        />
                        <Checkbox isSelected={corresponding} onChange={setCorresponding} label="Corresponding author" />
                        <Button type="submit" isLoading={busy} isDisabled={!email}>
                            Add member
                        </Button>
                    </form>
                )}
                <ErrorAlert error={error} />
            </Section>
            <Section title="Approval history" description="Approvals are never edited. An invalidated approval stays in the history and a new signature is recorded.">
                {approvals.isLoading && <Loading label="Loading approvals" />}
                {approvals.data && approvals.data.items.length === 0 && <p className="text-sm text-tertiary">No approvals recorded yet.</p>}
                <ul className="flex flex-col gap-2">
                    {approvals.data?.items.map((a) => (
                        <li key={a.id} className="flex flex-col gap-1 rounded-xl bg-primary p-4 text-sm ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold text-primary">{a.gate}</span>
                                <StatusBadge status={a.status} />
                                <span className="text-xs text-tertiary">
                                    {a.approver} ({a.approver_role}) · {formatDateTime(a.decided_at)} · declaration {a.declaration_version}
                                </span>
                            </div>
                            <p className="text-xs text-tertiary">Content manifest {shortHash(a.content_manifest_hash, 16)} · binds {a.bound_artifacts.length} artifact(s)</p>
                            {a.rationale && <p className="text-secondary">Rationale: {a.rationale}</p>}
                            {a.invalidation_reason && <p className="text-utility-amber-700">Invalidated {formatDateTime(a.invalidated_at)}: {a.invalidation_reason}</p>}
                        </li>
                    ))}
                </ul>
                <Button color="link-color" href={`/projects/${project.id}/activity`}>
                    Open the full audit history
                </Button>
            </Section>
        </div>
    );
}
