"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ModelProviderChoice } from "@/components/model-provider/model-provider-card";
import { useProject } from "@/components/project/project-context";
import { BudgetBar, CostLimitNotice } from "@/components/research/cost-limit-notice";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { DataFlow, ModelProviderView, Provider, Usage } from "@/lib/api/types";
import { formatDateTime, formatMoney, humanize } from "@/lib/format";
import { announceProviderChange } from "@/lib/model-provider";

export default function CostsPage() {
    const { project, reload } = useProject();
    const usage = useResource<Usage>(project ? `/v1/projects/${project.id}/usage` : null);
    const flow = useResource<DataFlow>(project ? `/v1/projects/${project.id}/data-flow` : null);
    const providers = useResource<Provider[]>("/v1/providers");
    const modelChoice = useResource<ModelProviderView>(project ? `/v1/projects/${project.id}/model-provider` : null);
    const [capOpen, setCapOpen] = useState(false);
    const [cap, setCap] = useState("");
    const [capReason, setCapReason] = useState("");
    const [attestOpen, setAttestOpen] = useState(false);
    const [provider, setProvider] = useState("");
    const [kinds, setKinds] = useState<string[]>([]);
    const [maxClass, setMaxClass] = useState("public");
    const [accepted, setAccepted] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    if (!project) return null;
    const isOwner = project.my_role === "owner";
    const u = usage.data;
    const modelProviders = (providers.data ?? []).filter((p) => p.kind === "model" && p.key !== "fixture");

    const run = async (fn: () => Promise<unknown>, after: () => void) => {
        setBusy(true);
        setError(undefined);
        try {
            await fn();
            after();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    const openAttest = (key: string) => {
        setProvider(key);
        setKinds([]);
        setAccepted(false);
        setAttestOpen(true);
    };

    return (
        <div className="flex flex-col gap-10">
            <Section
                id="ai-provider"
                title="AI provider"
                description="How this project reaches Claude. Your choice applies to every AI step in this project; calls to any other provider are refused."
            >
                {modelChoice.isLoading && !modelChoice.data && <Loading label="Loading AI provider" />}
                <ErrorAlert error={modelChoice.error} />
                {modelChoice.data && (
                    <ModelProviderChoice
                        view={modelChoice.data}
                        onSelect={async (key) => {
                            await api.put(`/v1/projects/${project.id}/model-provider`, { provider: key });
                            await modelChoice.reload();
                            announceProviderChange(project.id);
                        }}
                        onAttest={openAttest}
                    />
                )}
            </Section>
            {usage.isLoading && <Loading label="Loading costs" />}
            <ErrorAlert error={usage.error} />
            {u && (
                <>
                    <CostLimitNotice budget={u.budget} />
                    <Section
                        title="Budget"
                        description={u.note}
                        actions={
                            isOwner && (
                                <Button
                                    color="secondary"
                                    onClick={() => {
                                        setCap(String(u.budget.cap_cents / 100));
                                        setCapReason("");
                                        setCapOpen(true);
                                    }}
                                >
                                    Change cost cap
                                </Button>
                            )
                        }
                    >
                        <div className="rounded-2xl bg-primary p-5 ring-1 ring-secondary">
                            <BudgetBar budget={u.budget} />
                        </div>
                        {u.alerts.length > 0 && (
                            <ul className="flex flex-wrap gap-2">
                                {u.alerts.map((a) => (
                                    <li key={`${a.threshold_pct}-${a.cap_cents}`}>
                                        <StatusBadge status={a.threshold_pct >= 100 ? "blocked" : "waiting_human"} label={`${a.threshold_pct}% reached ${formatDateTime(a.at)}`} />
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Section>
                    <Section title="Usage by category">
                        {u.by_category.length === 0 ? (
                            <p className="text-sm text-tertiary">No usage recorded yet.</p>
                        ) : (
                            <div className="overflow-x-auto rounded-2xl bg-primary ring-1 ring-secondary">
                                <table className="w-full min-w-[640px] text-left text-sm">
                                    <thead className="bg-secondary text-xs text-tertiary">
                                        <tr>
                                            {["Category", "Provider", "Billed to", "Units", "Actual", "Estimated"].map((h) => (
                                                <th key={h} scope="col" className="px-4 py-2 font-medium">
                                                    {h}
                                                </th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-secondary">
                                        {u.by_category.map((c) => (
                                            <tr key={`${c.category}-${c.provider}-${c.billing_source}`}>
                                                <td className="px-4 py-2 text-primary">{humanize(c.category)}</td>
                                                <td className="px-4 py-2 text-secondary">{c.provider}</td>
                                                <td className="px-4 py-2 text-secondary">{c.billing_source === "platform" ? "Platform" : "Your connected account"}</td>
                                                <td className="px-4 py-2 text-secondary">{c.units.toLocaleString()}</td>
                                                <td className="px-4 py-2 text-secondary">{formatMoney(c.actual_cost_cents, u.budget.currency)}</td>
                                                <td className="px-4 py-2 text-tertiary">{formatMoney(c.estimated_cost_cents, u.budget.currency)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </Section>
                    <Section title="Model calls" description="Every model call is authorized against provider terms, data classification, your data-flow permissions and the cost cap before it runs.">
                        {u.model_invocations.length === 0 ? (
                            <p className="text-sm text-tertiary">No model calls yet.</p>
                        ) : (
                            <ul className="flex flex-col gap-2">
                                {u.model_invocations.map((m) => (
                                    <li key={m.id} className="flex flex-col gap-1 rounded-xl bg-primary p-3 text-sm ring-1 ring-secondary">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="font-medium text-primary">{humanize(m.agent)}</span>
                                            <StatusBadge status={m.status === "denied" ? "blocked" : m.status === "succeeded" ? "succeeded" : m.status === "failed" ? "failed" : "running"} label={humanize(m.status)} />
                                            <span className="text-xs text-tertiary">
                                                {m.provider === "fixture" ? "Fixture output (test/demo only)" : `${m.provider} / ${m.model}`} · prompt {m.prompt_version} · {m.data_classification}
                                            </span>
                                        </div>
                                        <p className="text-xs text-tertiary">
                                            {m.input_tokens ?? 0} in / {m.output_tokens ?? 0} out tokens · {formatMoney(m.actual_cost_cents ?? m.estimated_cost_cents, u.budget.currency)} · {formatDateTime(m.created_at)}
                                        </p>
                                        {m.denial_reason && <p className="text-sm text-error-primary">Denied: {m.denial_reason}</p>}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Section>
                </>
            )}
            <Section
                title="Data-flow permissions"
                description="No unpublished manuscript, coauthor material, uploaded paper or confidential dataset is sent to a model provider without the project owner's attestation."
                actions={
                    isOwner && (
                        <Button color="secondary" onClick={() => openAttest(modelChoice.data?.selected && modelChoice.data.selected !== "fixture" ? modelChoice.data.selected : (modelProviders[0]?.key ?? ""))}>
                            Attest a data flow
                        </Button>
                    )
                }
            >
                <ErrorAlert error={flow.error} />
                {flow.data && flow.data.items.length === 0 && <p className="text-sm text-tertiary">No data flows attested. Model calls on project data are refused until you attest one.</p>}
                <ul className="flex flex-col gap-2">
                    {flow.data?.items.map((a) => (
                        <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-primary p-3 text-sm ring-1 ring-secondary">
                            <div>
                                <p className="font-medium text-primary">{a.provider_key}</p>
                                <p className="text-xs text-tertiary">
                                    {a.data_kinds.map(humanize).join(", ")} · up to {a.max_classification} · attested {formatDateTime(a.attested_at)}
                                </p>
                            </div>
                            {a.revoked_at ? (
                                <StatusBadge status="cancelled" label={`Revoked ${formatDateTime(a.revoked_at)}`} />
                            ) : (
                                isOwner && (
                                    <Button size="sm" color="secondary-destructive" onClick={() => run(() => api.del(`/v1/projects/${project.id}/data-flow/${a.id}`), () => void flow.reload())}>
                                        Revoke
                                    </Button>
                                )
                            )}
                        </li>
                    ))}
                </ul>
            </Section>
            <DialogShell
                isOpen={capOpen}
                onOpenChange={setCapOpen}
                title="Change the cost cap"
                description="The ceiling is never raised automatically. Your decision and reason are recorded."
                footer={
                    <>
                        <Button color="secondary" onClick={() => setCapOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            isLoading={busy}
                            isDisabled={capReason.trim().length < 3 || !cap}
                            onClick={() =>
                                run(
                                    () => api.post(`/v1/projects/${project.id}/budget`, { new_cap_cents: Math.round(Number(cap) * 100), expected_version: project.version, rationale: capReason }),
                                    () => {
                                        setCapOpen(false);
                                        void usage.reload();
                                        void reload();
                                    },
                                )
                            }
                        >
                            Save cap
                        </Button>
                    </>
                }
            >
                <Input label={`New cap (${u?.budget.currency ?? "USD"})`} type="number" value={cap} onChange={setCap} />
                <TextArea label="Reason" isRequired value={capReason} onChange={setCapReason} rows={2} />
                <ErrorAlert error={error} />
            </DialogShell>
            <DialogShell
                isOpen={attestOpen}
                onOpenChange={setAttestOpen}
                title="Attest a data flow"
                size="lg"
                footer={
                    <>
                        <Button color="secondary" onClick={() => setAttestOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            isLoading={busy}
                            isDisabled={!accepted || !provider || kinds.length === 0}
                            onClick={() =>
                                run(
                                    () => api.post(`/v1/projects/${project.id}/data-flow`, { provider_key: provider, data_kinds: kinds, max_classification: maxClass, attestation_accepted: accepted }),
                                    () => {
                                        setAttestOpen(false);
                                        void flow.reload();
                                        void modelChoice.reload();
                                    },
                                )
                            }
                        >
                            Record attestation
                        </Button>
                    </>
                }
            >
                <NativeSelect
                    label="Model provider"
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                    options={modelProviders.length ? modelProviders.map((p) => ({ label: `${p.display_name} (${humanize(p.gate_status)})`, value: p.key })) : [{ label: "No model provider is registered", value: "" }]}
                />
                {(() => {
                    const p = modelProviders.find((x) => x.key === provider);
                    return p?.gate_notes ? <p className="text-sm text-tertiary">{p.gate_notes}</p> : null;
                })()}
                <fieldset className="flex flex-col gap-2">
                    <legend className="mb-1 text-sm font-medium text-secondary">Data that may be sent</legend>
                    {(flow.data?.data_kinds ?? []).map((k) => (
                        <Checkbox key={k} label={humanize(k)} isSelected={kinds.includes(k)} onChange={(on) => setKinds((ks) => (on ? [...ks, k] : ks.filter((x) => x !== k)))} />
                    ))}
                </fieldset>
                <NativeSelect
                    label="Highest classification"
                    value={maxClass}
                    onChange={(e) => setMaxClass(e.target.value)}
                    options={[
                        { label: "Public", value: "public" },
                        { label: "Internal", value: "internal" },
                        { label: "Restricted", value: "restricted" },
                    ]}
                />
                <blockquote className="rounded-xl bg-secondary p-4 font-display text-sm text-primary">{flow.data?.attestation_text}</blockquote>
                <Checkbox isSelected={accepted} onChange={setAccepted} label="This statement is true for this project" />
                <ErrorAlert error={error} />
            </DialogShell>
        </div>
    );
}
