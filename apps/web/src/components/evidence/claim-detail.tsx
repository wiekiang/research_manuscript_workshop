"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { StatusBadge } from "@/components/research/status-badge";
import { PassageQuote } from "@/components/evidence/passage-quote";
import { VerificationMethodLabel } from "@/components/research/verification-method-label";
import { api } from "@/lib/api/client";
import type { ClaimEntry, PaperEntry, PassageEntry } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { CATEGORY_LABEL, CLAIM_STATUS, requirementText, verificationProvider } from "@/lib/literature";

export function ClaimStatusBadge({ claim }: { claim: Pick<ClaimEntry, "status"> }) {
    const spec = CLAIM_STATUS[claim.status] ?? { label: claim.status, status: "claim_unverified" };
    return <StatusBadge status={spec.status} label={spec.label} />;
}

interface DetailProps {
    claim: ClaimEntry;
    passages: Map<string, PassageEntry>;
    papers: Map<string, PaperEntry>;
    requirements: Record<string, string>;
    policyVersion: string;
    canEdit: boolean;
    onClose: () => void;
    onChanged: () => void;
}

/** Everything that went into a claim's status, with each check labelled by who or what performed it. */
export function ClaimDetail({ claim, passages, papers, requirements, policyVersion, canEdit, onClose, onChanged }: DetailProps) {
    const [panel, setPanel] = useState<"none" | "support" | "verify" | "revise">("none");
    const d = claim.decision;
    return (
        <DialogShell isOpen onOpenChange={(o) => !o && onClose()} title={`${claim.claim_key}: claim detail`} size="lg" description={claim.proposition}>
            <div data-testid="claim-detail" className="flex max-h-[70vh] flex-col gap-5 overflow-y-auto pr-1">
                <div className="flex flex-wrap items-center gap-2">
                    <ClaimStatusBadge claim={claim} />
                    <span className="text-xs text-tertiary">
                        {claim.kind.replace("_", " ")} · {CATEGORY_LABEL[claim.category] ?? claim.category}
                        {claim.critical ? " · critical claim" : ""} · {claim.gate_eligible ? "usable at gates under the current policy" : "not usable at gates"} · origin {claim.origin}
                    </span>
                </div>
                <section aria-label="Policy evaluation" className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-secondary">
                        Policy evaluation ({d.policy_version ?? "—"}, rule {d.rule_id ?? "—"}){d.policy_version && d.policy_version !== policyVersion ? " — decided under a superseded policy" : ""}
                    </h3>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                            <p className="text-xs font-medium text-success-primary">Satisfied</p>
                            <ul className="list-disc pl-5 text-sm text-secondary">
                                {(d.satisfied ?? []).length === 0 ? <li>None yet</li> : (d.satisfied ?? []).map((r) => <li key={r}>{requirementText(r, requirements)}</li>)}
                            </ul>
                        </div>
                        <div>
                            <p className="text-xs font-medium text-warning-primary">Outstanding</p>
                            <ul className="list-disc pl-5 text-sm text-secondary" data-testid="outstanding-requirements">
                                {(d.outstanding ?? []).length === 0 ? <li>None</li> : (d.outstanding ?? []).map((r) => <li key={r}>{requirementText(r, requirements)}</li>)}
                            </ul>
                            {d.human_required && <p className="mt-1 text-xs text-warning-primary">A human must act; a model check cannot satisfy the outstanding requirement.</p>}
                        </div>
                    </div>
                </section>
                <section aria-label="Evidence relationships" className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-secondary">Evidence relationships</h3>
                    {claim.supports.length === 0 && <p className="text-sm text-tertiary">No evidence linked.</p>}
                    <ul className="flex flex-col gap-2">
                        {claim.supports.map((s) => {
                            const p = s.passage_id ? passages.get(s.passage_id) : undefined;
                            const paper = s.paper_id ? papers.get(s.paper_id) : p ? papers.get(p.paper_id) : undefined;
                            return (
                                <li key={s.id} className="flex flex-col gap-1 rounded-lg bg-secondary p-3">
                                    <span className="text-xs font-medium text-secondary">
                                        {s.relation.replace("_", " ")} {s.is_current ? "" : "(no longer current)"} {paper ? `· ${paper.title}` : ""}
                                        {s.result_ref ? ` · result ${s.result_ref}` : ""}
                                    </span>
                                    {p && <PassageQuote passage={p} compact />}
                                </li>
                            );
                        })}
                    </ul>
                </section>
                <section aria-label="Verification records" className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-secondary">Verification records</h3>
                    <p className="text-xs text-tertiary">Model-assisted checks are labelled as such and are never shown as human verification.</p>
                    <ul className="flex flex-col gap-2" data-testid="verification-records">
                        {claim.verifications.map((v) => (
                            <li key={v.id} data-testid="verification-record" data-method={v.method} data-check={v.check} className="flex flex-col gap-1 rounded-lg p-3 ring-1 ring-secondary">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-sm font-medium text-primary">
                                        {v.check.replace("_", " ")}: {v.outcome.replace("_", " ")}
                                    </span>
                                    <VerificationMethodLabel method={v.method} provider={verificationProvider(v)} />
                                    {!v.is_current && <span className="text-xs text-tertiary">(superseded)</span>}
                                </div>
                                <span className="text-xs text-tertiary">
                                    {v.verifier} v{v.verifier_version} · {formatDateTime(v.at)}
                                    {v.requires_human_confirmation ? " · requires human confirmation" : ""}
                                </span>
                                {v.uncertainty && <span className="text-xs text-secondary">Uncertainty: {v.uncertainty}</span>}
                                {typeof v.evidence?.note === "string" && v.evidence.note && <span className="text-xs text-secondary">Note: {v.evidence.note as string}</span>}
                                {typeof v.evidence?.statement === "string" && <span className="text-xs text-secondary">Statement: {v.evidence.statement as string}</span>}
                            </li>
                        ))}
                    </ul>
                </section>
                <section aria-label="Decision history" className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-secondary">Decision history</h3>
                    <ol className="flex flex-col gap-1 text-sm">
                        {[...claim.decisions].reverse().map((dec, i) => (
                            <li key={i} className="flex flex-wrap items-center gap-2">
                                <StatusBadge status={dec.state} />
                                <span className="text-secondary">
                                    {dec.policy_version} · {dec.rule_id} · {dec.status}
                                </span>
                                <span className="text-xs text-tertiary">{formatDateTime(dec.at)}</span>
                            </li>
                        ))}
                    </ol>
                </section>
                {canEdit && (
                    <div className="flex flex-wrap gap-2">
                        <Button size="sm" color="secondary" onClick={() => setPanel("support")}>
                            Link evidence
                        </Button>
                        <Button size="sm" onClick={() => setPanel("verify")}>
                            Verify
                        </Button>
                        <Button size="sm" color="secondary" onClick={() => setPanel("revise")}>
                            Revise claim
                        </Button>
                    </div>
                )}
                {panel === "support" && <SupportForm claim={claim} passages={passages} papers={papers} onDone={() => { setPanel("none"); onChanged(); }} />}
                {panel === "verify" && <VerifyForm claim={claim} onDone={() => { setPanel("none"); onChanged(); }} />}
                {panel === "revise" && <ReviseForm claim={claim} onDone={() => { setPanel("none"); onChanged(); onClose(); }} />}
            </div>
        </DialogShell>
    );
}

function SupportForm({ claim, passages, papers, onDone }: { claim: ClaimEntry; passages: Map<string, PassageEntry>; papers: Map<string, PaperEntry>; onDone: () => void }) {
    const [target, setTarget] = useState("");
    const [relation, setRelation] = useState("supports");
    const [resultRef, setResultRef] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const options = [
        { label: "Choose evidence…", value: "" },
        ...[...passages.values()].map((p) => ({ label: `Passage: “${p.quote.slice(0, 70)}…” (${papers.get(p.paper_id)?.title.slice(0, 40) ?? "paper"})`, value: `passage:${p.id}` })),
        ...[...papers.values()].map((p) => ({ label: `Paper: ${p.title.slice(0, 80)}`, value: `paper:${p.id}` })),
    ];
    return (
        <form
            aria-label="Link evidence"
            className="flex flex-col gap-3 rounded-xl bg-secondary p-4"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                const [kind, id] = target.split(":");
                try {
                    await api.post(`/v1/claims/${claim.id}/support`, {
                        passage_id: kind === "passage" ? id : null,
                        paper_id: kind === "paper" ? id : null,
                        result_ref: resultRef || null,
                        relation,
                    });
                    onDone();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <NativeSelect label="Evidence" value={target} onChange={(e) => setTarget(e.target.value)} options={options} />
            <Input label="Committed result reference (optional)" value={resultRef} onChange={setResultRef} />
            <NativeSelect
                label="Relation"
                value={relation}
                onChange={(e) => setRelation(e.target.value)}
                options={[
                    { label: "Supports", value: "supports" },
                    { label: "Contradicts", value: "contradicts" },
                    { label: "Qualifies", value: "qualifies" },
                    { label: "Closest prior work", value: "closest_work" },
                ]}
            />
            <ErrorAlert error={error} />
            <div>
                <Button type="submit" size="sm" isLoading={busy} isDisabled={!target && !resultRef}>
                    Link evidence
                </Button>
            </div>
        </form>
    );
}

function VerifyForm({ claim, onDone }: { claim: ClaimEntry; onDone: () => void }) {
    const [support, setSupport] = useState<"" | "yes" | "no">("");
    const [supportNote, setSupportNote] = useState("");
    const [judgment, setJudgment] = useState("");
    const [closest, setClosest] = useState("");
    const [units, setUnits] = useState("");
    const [srcUrl, setSrcUrl] = useState("");
    const [srcNote, setSrcNote] = useState("");
    const [contradiction, setContradiction] = useState("");
    const [strength, setStrength] = useState("");
    const [model, setModel] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [queued, setQueued] = useState(false);
    return (
        <form
            aria-label="Verify claim"
            className="flex flex-col gap-3 rounded-xl bg-secondary p-4"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                try {
                    const res = await api.post<{ task: unknown }>(`/v1/claims/${claim.id}/verify`, {
                        human_support: support === "" ? null : support === "yes",
                        human_support_note: supportNote || null,
                        human_judgment: judgment || null,
                        closest_work_note: closest || null,
                        units: units || null,
                        authoritative_source_url: srcUrl || null,
                        authoritative_source_note: srcNote || null,
                        resolve_contradiction: contradiction || null,
                        resolve_strength_mismatch: strength || null,
                        request_model_assessment: model,
                    });
                    if (res.task) setQueued(true);
                    onDone();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <p className="text-xs text-tertiary">Your entries are recorded as human checks under your name. The model assessment is recorded separately as model-assisted.</p>
            <NativeSelect
                label="Your support assessment"
                value={support}
                onChange={(e) => setSupport(e.target.value as "" | "yes" | "no")}
                options={[
                    { label: "No assessment", value: "" },
                    { label: "The evidence supports this claim", value: "yes" },
                    { label: "The evidence does not support this claim", value: "no" },
                ]}
            />
            <Input label="Support note" value={supportNote} onChange={setSupportNote} />
            <TextArea label="Your scientific judgment" value={judgment} onChange={setJudgment} rows={2} />
            <TextArea label="Closest prior work / alternative explanations assessed" value={closest} onChange={setClosest} rows={2} />
            <Input label="Units or denominator" value={units} onChange={setUnits} />
            <div className="grid gap-3 sm:grid-cols-2">
                <Input label="Authoritative source URL" type="url" value={srcUrl} onChange={setSrcUrl} />
                <Input label="Authoritative source note" value={srcNote} onChange={setSrcNote} />
            </div>
            <Input label="Resolve contradiction (explain)" value={contradiction} onChange={setContradiction} />
            <Input label="Resolve strength mismatch (explain)" value={strength} onChange={setStrength} />
            <Checkbox isSelected={model} onChange={setModel} label="Request a model-assisted support assessment of the linked passages" />
            <ErrorAlert error={error} />
            {queued && <p className="text-sm text-success-primary">Model-assisted assessment queued.</p>}
            <div>
                <Button type="submit" size="sm" isLoading={busy}>
                    Record and re-evaluate
                </Button>
            </div>
        </form>
    );
}

function ReviseForm({ claim, onDone }: { claim: ClaimEntry; onDone: () => void }) {
    const [text, setText] = useState(claim.proposition);
    const [scope, setScope] = useState(claim.normalized?.scope ?? "");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <form
            aria-label="Revise claim"
            className="flex flex-col gap-3 rounded-xl bg-secondary p-4"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                try {
                    await api.post(`/v1/claims/${claim.id}/revise`, { proposition: text, scope: scope || null });
                    onDone();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <p className="text-xs text-tertiary">A changed qualifier, number, population or causal strength creates a new claim key; verification starts again and this claim is superseded.</p>
            <TextArea label="Revised proposition" value={text} onChange={setText} rows={3} />
            <Input label="Scope" value={scope} onChange={setScope} />
            <ErrorAlert error={error} />
            <div>
                <Button type="submit" size="sm" isLoading={busy} isDisabled={text.trim().length < 5 || text === claim.proposition}>
                    Create revised claim
                </Button>
            </div>
        </form>
    );
}
