"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { ProfileEditor } from "@/components/discovery/profile-editor";
import { ModelConnectionsCard } from "@/components/model-provider/model-connections-card";
import { ErrorAlert } from "@/components/research/error-alert";
import { MfaSetup } from "@/components/research/mfa-setup";
import { Loading, PageHeader, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { Provider, WorkspaceMember } from "@/lib/api/types";
import { COPY } from "@/lib/copy";
import { humanize } from "@/lib/format";
import { useSession } from "@/providers/session";

const GATE_LABEL: Record<string, string> = {
    cleared: "Cleared for production",
    development_only: "Development use; production review outstanding",
    pending: "Not yet available",
    blocked: "Not available (blocked)",
};

function ProviderRow({ p }: { p: Provider }) {
    const connectable = p.requires_user_connection && p.enabled && p.gate_status === "cleared";
    return (
        <li className="flex flex-col gap-2 p-4">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-primary">{p.display_name}</span>
                <span className="text-xs text-tertiary">{humanize(p.kind)}</span>
                <StatusBadge status={p.enabled && p.gate_status !== "blocked" ? "current" : p.gate_status === "blocked" ? "blocked" : "queued"} label={GATE_LABEL[p.gate_status] ?? p.gate_status} />
            </div>
            {p.gate_notes && <p className="text-sm text-tertiary">{p.gate_notes}</p>}
            {p.attribution && <p className="text-xs text-tertiary">Attribution: {p.attribution}</p>}
            <div className="flex flex-wrap gap-4 text-xs">
                {p.docs_url && (
                    <a className="text-brand-secondary underline" href={p.docs_url} target="_blank" rel="noreferrer">
                        API documentation
                    </a>
                )}
                {p.terms_url && (
                    <a className="text-brand-secondary underline" href={p.terms_url} target="_blank" rel="noreferrer">
                        Terms
                    </a>
                )}
            </div>
            {/* Researcher-owned connections appear only after the provider's rights gate is cleared (spec §1, §2.5). */}
            {connectable && <p className="text-sm text-secondary">{COPY.provider_connection_template.replace("{provider}", p.display_name)}</p>}
        </li>
    );
}

export default function SettingsPage() {
    const { me, refresh, currentWorkspace } = useSession();
    const isAdmin = currentWorkspace?.role === "workspace_admin";
    const members = useResource<WorkspaceMember[]>(me?.session.tenant_id ? "/v1/workspaces/current/members" : null);
    const providers = useResource<Provider[]>("/v1/providers");
    const [wsName, setWsName] = useState("");
    const [email, setEmail] = useState("");
    const [role, setRole] = useState("member");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    if (!me) return <Loading />;

    const run = async (fn: () => Promise<unknown>) => {
        setBusy(true);
        setError(undefined);
        try {
            await fn();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    // Elicit is blocked by its API terms; it must not appear as a connectable integration at all.
    const shownProviders = (providers.data ?? []).filter((p) => p.key !== "elicit" || p.gate_status === "cleared");

    return (
        <div className="flex flex-col gap-10">
            <PageHeader title="Settings" description="Your account, your workspace and the external services the platform may use." />
            <Section title="Account">
                <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div>
                        <dt className="text-xs text-tertiary">Name</dt>
                        <dd className="text-sm text-primary">{me.user.display_name}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-tertiary">Email</dt>
                        <dd className="text-sm text-primary">{me.user.email}</dd>
                    </div>
                    <div>
                        <dt className="text-xs text-tertiary">This session</dt>
                        <dd className="text-sm text-primary">{me.session.mfa ? "Verified with an authentication code" : "Password only"}</dd>
                    </div>
                </dl>
                <MfaSetup enabled={me.user.mfa_enabled} onEnabled={() => void refresh()} />
            </Section>
            <Section
                id="ai-provider-connections"
                title="AI provider connections"
                description="Connect your own Anthropic API key so projects you own can use it. Each project's owner then chooses its AI provider on the project's Costs page."
            >
                <ModelConnectionsCard />
            </Section>
            <Section title="Default research profile" description="Used for conference discovery in every project unless a project sets its own values.">
                <ProfileEditor />
            </Section>
            <Section title="Workspaces">
                <form
                    className="flex flex-col gap-3 sm:flex-row sm:items-end"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void run(async () => {
                            await api.post("/v1/workspaces", { name: wsName });
                            setWsName("");
                            await refresh();
                        });
                    }}
                >
                    <Input label="Create another workspace" value={wsName} onChange={setWsName} className="flex-1" />
                    <Button type="submit" isLoading={busy} isDisabled={!wsName.trim()}>
                        Create workspace
                    </Button>
                </form>
            </Section>
            {me.session.tenant_id && (
                <Section title={`Members of ${currentWorkspace?.name ?? "this workspace"}`} description="Adding or removing members requires a workspace admin signed in with multi-factor authentication.">
                    <ul className="flex flex-col divide-y divide-secondary rounded-2xl bg-primary ring-1 ring-secondary">
                        {members.data?.map((m) => (
                            <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 p-4">
                                <div>
                                    <p className="text-sm font-semibold text-primary">{m.display_name}</p>
                                    <p className="text-xs text-tertiary">{m.email}</p>
                                </div>
                                <div className="flex items-center gap-2 text-xs text-tertiary">
                                    {humanize(m.role)} · {m.status} · {m.mfa_enabled ? "MFA on" : "MFA off"}
                                    {isAdmin && m.user_id !== me.user.id && m.status === "active" && (
                                        <Button size="sm" color="secondary-destructive" onClick={() => run(async () => { await api.del(`/v1/workspaces/current/members/${m.user_id}`); await members.reload(); })}>
                                            Remove
                                        </Button>
                                    )}
                                </div>
                            </li>
                        ))}
                    </ul>
                    {isAdmin && (
                        <form
                            className="flex flex-col gap-3 sm:flex-row sm:items-end"
                            onSubmit={(e) => {
                                e.preventDefault();
                                void run(async () => {
                                    await api.post("/v1/workspaces/current/members", { email, role });
                                    setEmail("");
                                    await members.reload();
                                });
                            }}
                        >
                            <Input label="Add an existing account by email" type="email" value={email} onChange={setEmail} className="flex-1" />
                            <NativeSelect label="Role" value={role} onChange={(e) => setRole(e.target.value)} className="sm:w-48" options={[{ label: "Member", value: "member" }, { label: "Workspace admin", value: "workspace_admin" }]} />
                            <Button type="submit" isLoading={busy} isDisabled={!email}>
                                Add member
                            </Button>
                        </form>
                    )}
                </Section>
            )}
            <ErrorAlert error={error} />
            <Section
                title="External services"
                description="Each provider is used only within its recorded terms. Literature search works without any paid subscription; optional researcher-owned connections appear here only after their rights review is complete."
            >
                {providers.isLoading && <Loading label="Loading providers" />}
                <ul className="flex flex-col divide-y divide-secondary rounded-2xl bg-primary ring-1 ring-secondary">
                    {shownProviders
                        .filter((p) => p.key !== "fixture")
                        .map((p) => (
                            <ProviderRow key={p.key} p={p} />
                        ))}
                </ul>
            </Section>
        </div>
    );
}
