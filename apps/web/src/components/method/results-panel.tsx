"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { ContributionEntry, MetricValue, ProtocolEntry, ResultEntry } from "@/lib/api/types";
import { humanize } from "@/lib/format";

const FILE_ROLES = ["raw_data", "predictions", "code", "environment", "analysis_script", "figure", "other"];

export function assuranceStatus(r: Pick<ResultEntry, "assessment" | "assurance_level">): string {
    return r.assessment ? `assurance_${r.assessment.assurance_level}` : "assurance_pending";
}

interface MetricRow {
    name: string;
    value: string;
    unit: string;
    n: string;
    numerator: string;
    denominator: string;
    condition: string;
}
const EMPTY_METRIC: MetricRow = { name: "", value: "", unit: "", n: "", numerator: "", denominator: "", condition: "" };

const num = (s: string) => (s.trim() === "" ? null : Number(s));

/**
 * Supplied result manifests, bound to the frozen protocol hash. Assurance levels come from the deterministic
 * assessor; wording limits are shown verbatim and govern how a result may be described.
 */
export function ResultsPanel({
    projectId,
    results,
    attestation,
    frozen,
    contributions,
    canEdit,
    onChanged,
}: {
    projectId: string;
    results: ResultEntry[];
    attestation: string | undefined;
    frozen: ProtocolEntry | undefined;
    contributions: ContributionEntry[];
    canEdit: boolean;
    onChanged: () => void;
}) {
    const [open, setOpen] = useState(false);
    const [claimFor, setClaimFor] = useState<ResultEntry | null>(null);
    return (
        <Section
            title="Results"
            description={frozen ? `Results are accepted only against frozen protocol v${frozen.version} (hash ${frozen.content_hash.slice(0, 16)}).` : "Results can be supplied only after the protocol is frozen at H2."}
            actions={
                canEdit &&
                frozen && (
                    <Button size="sm" color="secondary" onClick={() => setOpen(true)}>
                        Supply a result
                    </Button>
                )
            }
        >
            {results.length === 0 && <p className="text-sm text-tertiary">No results supplied yet.</p>}
            <ul className="flex flex-col gap-3">
                {results.map((r) => (
                    <li key={r.id} data-testid="result-row" data-assurance={r.assessment?.assurance_level ?? "pending"} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs text-tertiary">{r.result_key}</span>
                            <span className="text-sm font-medium text-primary">{r.title}</span>
                            <StatusBadge status={assuranceStatus(r)} />
                            {!r.is_current && <StatusBadge status="superseded" />}
                            {r.manifest.synthetic_or_simulated && <span className="text-xs text-warning-primary">Synthetic or simulated data</span>}
                        </div>
                        <table className="w-full text-left text-xs">
                            <thead className="text-tertiary">
                                <tr>
                                    <th className="py-1 pr-2 font-medium">Metric</th>
                                    <th className="py-1 pr-2 font-medium">Value</th>
                                    <th className="py-1 pr-2 font-medium">Unit</th>
                                    <th className="py-1 pr-2 font-medium">n</th>
                                    <th className="py-1 pr-2 font-medium">Condition</th>
                                </tr>
                            </thead>
                            <tbody className="text-secondary">
                                {r.manifest.metrics.map((m: MetricValue, i: number) => (
                                    <tr key={i}>
                                        <td className="py-0.5 pr-2">{m.name}</td>
                                        <td className="py-0.5 pr-2">
                                            {m.value}
                                            {m.numerator != null && m.denominator != null ? ` (${m.numerator}/${m.denominator})` : ""}
                                        </td>
                                        <td className="py-0.5 pr-2">{m.unit ?? "—"}</td>
                                        <td className="py-0.5 pr-2">{m.n ?? "—"}</td>
                                        <td className="py-0.5 pr-2">{m.condition ?? "—"}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        {r.assessment ? (
                            <div className="flex flex-col gap-1 text-sm">
                                {r.assessment.wording_limits.length > 0 && (
                                    <div data-testid="wording-limits">
                                        <p className="font-medium text-secondary">How this result may be described</p>
                                        <ul className="list-disc pl-5 text-secondary">
                                            {r.assessment.wording_limits.map((w) => (
                                                <li key={w}>{w}</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}
                                {r.assessment.missing.length > 0 && <p className="text-tertiary">Missing: {r.assessment.missing.join("; ")}</p>}
                                {r.assessment.impossible_checks.length > 0 && <p className="text-tertiary">Checks not possible: {r.assessment.impossible_checks.join("; ")}</p>}
                                {r.assessment.blockers.length > 0 && <p className="text-error-primary">Blockers: {r.assessment.blockers.join("; ")}</p>}
                                <p className="text-xs text-tertiary">Assessor {r.assessment.assessor} (deterministic)</p>
                            </div>
                        ) : (
                            <p className="text-sm text-tertiary">Assessment pending: do not report this result yet.</p>
                        )}
                        {canEdit && r.assessment && (
                            <div>
                                <Button size="sm" color="secondary" onClick={() => setClaimFor(r)}>
                                    Register a result claim
                                </Button>
                            </div>
                        )}
                    </li>
                ))}
            </ul>
            {frozen && <ResultDialog projectId={projectId} open={open} onClose={() => setOpen(false)} frozen={frozen} attestation={attestation} contributions={contributions} onDone={onChanged} />}
            <ResultClaimDialog projectId={projectId} result={claimFor} onClose={() => setClaimFor(null)} onDone={onChanged} />
        </Section>
    );
}

function ResultDialog({
    projectId,
    open,
    onClose,
    frozen,
    attestation,
    contributions,
    onDone,
}: {
    projectId: string;
    open: boolean;
    onClose: () => void;
    frozen: ProtocolEntry;
    attestation: string | undefined;
    contributions: ContributionEntry[];
    onDone: () => void;
}) {
    const [title, setTitle] = useState("");
    const [metrics, setMetrics] = useState<MetricRow[]>([{ ...EMPTY_METRIC }]);
    const [files, setFiles] = useState<Record<string, string>>({});
    const [origin, setOrigin] = useState("");
    const [rights, setRights] = useState("");
    const [methods, setMethods] = useState("");
    const [sample, setSample] = useState("");
    const [limitations, setLimitations] = useState("");
    const [runType, setRunType] = useState("confirmatory");
    const [synthetic, setSynthetic] = useState(false);
    const [attest, setAttest] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const withFiles = contributions.filter((c) => c.artifact_id);

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/results`, {
                title,
                protocol_version: frozen.version,
                protocol_hash: frozen.content_hash,
                data_origin: origin,
                data_rights: rights,
                methods,
                metrics: metrics
                    .filter((m) => m.name.trim() && m.value.trim())
                    .map((m) => ({
                        name: m.name.trim(),
                        value: Number(m.value),
                        unit: m.unit.trim() || null,
                        n: num(m.n),
                        numerator: num(m.numerator),
                        denominator: num(m.denominator),
                        condition: m.condition.trim() || null,
                    })),
                sample_size: num(sample),
                limitations,
                files: Object.entries(files)
                    .filter(([, role]) => role)
                    .map(([artifact_id, role]) => ({ role, artifact_id })),
                run_type: runType,
                synthetic_or_simulated: synthetic,
                attestation_accepted: attest,
            });
            onClose();
            onDone();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <DialogShell
            isOpen={open}
            onOpenChange={(o) => !o && onClose()}
            size="lg"
            title="Supply a result"
            description={`Bound to frozen protocol v${frozen.version}. The assurance level is assessed deterministically after you submit.`}
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button isLoading={busy} isDisabled={!attest || !title.trim()} onClick={submit}>
                        Submit result
                    </Button>
                </>
            }
        >
            <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
                <Input label="Title" isRequired value={title} onChange={setTitle} />
                <fieldset className="flex flex-col gap-2">
                    <legend className="text-sm font-medium text-secondary">Metrics</legend>
                    {metrics.map((m, i) => (
                        <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-7">
                            {(["name", "value", "unit", "n", "numerator", "denominator", "condition"] as const).map((k) => (
                                <Input
                                    key={k}
                                    size="sm"
                                    label={`${humanize(k)} ${i + 1}`}
                                    value={m[k]}
                                    onChange={(v) => setMetrics((ms) => ms.map((x, j) => (j === i ? { ...x, [k]: v } : x)))}
                                />
                            ))}
                        </div>
                    ))}
                    <div>
                        <Button size="sm" color="link-color" onClick={() => setMetrics((ms) => [...ms, { ...EMPTY_METRIC }])}>
                            Add a metric
                        </Button>
                    </div>
                </fieldset>
                {withFiles.length > 0 && (
                    <fieldset className="flex flex-col gap-2">
                        <legend className="text-sm font-medium text-secondary">Supporting files (from your contributions)</legend>
                        {withFiles.map((c) => (
                            <NativeSelect
                                key={c.id}
                                size="sm"
                                label={c.title}
                                value={files[c.artifact_id!] ?? ""}
                                onChange={(e) => setFiles((f) => ({ ...f, [c.artifact_id!]: e.target.value }))}
                                options={[{ label: "Not attached", value: "" }, ...FILE_ROLES.map((r) => ({ label: humanize(r), value: r }))]}
                            />
                        ))}
                    </fieldset>
                )}
                <TextArea label="Data origin" isRequired value={origin} onChange={setOrigin} rows={2} />
                <TextArea label="Data rights" isRequired value={rights} onChange={setRights} rows={2} />
                <TextArea label="Methods" isRequired value={methods} onChange={setMethods} rows={2} />
                <Input label="Sample size" value={sample} onChange={setSample} inputMode="numeric" />
                <TextArea label="Limitations" isRequired value={limitations} onChange={setLimitations} rows={2} />
                <NativeSelect
                    label="Run type"
                    value={runType}
                    onChange={(e) => setRunType(e.target.value)}
                    options={[
                        { label: "Confirmatory", value: "confirmatory" },
                        { label: "Exploratory", value: "exploratory" },
                    ]}
                />
                <Checkbox isSelected={synthetic} onChange={setSynthetic} label="These are synthetic or simulated data" />
                {attestation ? (
                    <>
                        <blockquote className="rounded-xl bg-secondary p-3 text-sm text-primary">{attestation}</blockquote>
                        <Checkbox isSelected={attest} onChange={setAttest} label="I make this attestation" />
                    </>
                ) : (
                    <p className="text-xs text-tertiary">The attestation text could not be loaded; reload the page.</p>
                )}
                <ErrorAlert error={error} />
            </div>
        </DialogShell>
    );
}

function ResultClaimDialog({ projectId, result, onClose, onDone }: { projectId: string; result: ResultEntry | null; onClose: () => void; onDone: () => void }) {
    const [proposition, setProposition] = useState("");
    const [metric, setMetric] = useState("");
    const [confirms, setConfirms] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [created, setCreated] = useState<{ claim_key: string; status: string; wording_limits: string[] }>();
    const metrics = result?.manifest.metrics ?? [];
    return (
        <DialogShell
            isOpen={result !== null}
            onOpenChange={(o) => {
                if (!o) {
                    onClose();
                    setCreated(undefined);
                }
            }}
            title={`Register a claim about ${result?.result_key ?? ""}`}
            description="An observed-result claim is linked to the committed result; its wording is limited by the assurance level."
            footer={
                created ? (
                    <Button
                        onClick={() => {
                            onClose();
                            setCreated(undefined);
                        }}
                    >
                        Done
                    </Button>
                ) : (
                    <>
                        <Button color="secondary" onClick={onClose}>
                            Cancel
                        </Button>
                        <Button
                            isLoading={busy}
                            isDisabled={proposition.trim().length < 5 || !(metric || metrics[0]?.name)}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    const r = await api.post<{ claim_key: string; status: string; wording_limits: string[] }>(
                                        `/v1/projects/${projectId}/results/${result!.id}/claims`,
                                        { proposition, metric_name: metric || metrics[0]?.name, researcher_confirms_match: confirms },
                                    );
                                    setCreated(r);
                                    setProposition("");
                                    onDone();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Register claim
                        </Button>
                    </>
                )
            }
        >
            {created ? (
                <div className="flex flex-col gap-2 text-sm" data-testid="result-claim-created">
                    <p className="text-primary">
                        {created.claim_key} registered · status {created.status}
                    </p>
                    <ul className="list-disc pl-5 text-secondary">
                        {created.wording_limits.map((w) => (
                            <li key={w}>{w}</li>
                        ))}
                    </ul>
                </div>
            ) : (
                <>
                    <NativeSelect label="Metric" value={metric || metrics[0]?.name || ""} onChange={(e) => setMetric(e.target.value)} options={metrics.map((m) => ({ label: `${m.name}${m.condition ? ` (${m.condition})` : ""}`, value: m.name }))} />
                    <TextArea label="Proposition" isRequired value={proposition} onChange={setProposition} rows={2} />
                    <Checkbox isSelected={confirms} onChange={setConfirms} label="I confirm the proposition matches the reported value" hint="Recorded as a human verification by you." />
                    <ErrorAlert error={error} />
                </>
            )}
        </DialogShell>
    );
}
