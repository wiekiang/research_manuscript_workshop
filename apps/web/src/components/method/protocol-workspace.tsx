"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { TaskProgress } from "@/components/cfp/task-progress";
import { ApprovalPanel } from "@/components/research/approval-panel";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { EthicsRights, ProtocolEntry, ProtocolList, ProtocolValidation, ReviewIssue, Task } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import { ReviewSpecEditor } from "@/components/synthesis/review-spec-editor";
import { SPEC_SECTION, isReviewStudyType } from "@/lib/synthesis";
import { EMPTY_ETHICS, EthicsForm } from "./ethics-form";

/** Every unmet H2 precondition as a sentence (the API re-checks them when freezing). */
export function h2BlockingReasons(v: ProtocolValidation | null): string[] {
    if (!v) return ["validation unavailable"];
    return [
        // Section ids are identifiers; anything else is a server-side check (e.g. review specification) shown verbatim.
        ...v.missing_sections.map((s) => (/^[a-z_]+$/.test(s) ? `section '${humanize(s)}' is empty` : s)),
        ...v.ethics_blockers,
        ...v.cost_flags,
        ...v.review,
        ...v.unresolved_blocker_issues.map((i) => `unresolved blocker in ${humanize(i.section)}: ${i.issue}`),
    ];
}

interface Props {
    projectId: string;
    list: ProtocolList | undefined;
    tasks: Task[];
    canEdit: boolean;
    isOwner: boolean;
    h2Declaration: string | undefined;
    onChanged: () => void;
    /** The selected study type; review types get a structured review-specification editor. */
    studyType?: string | null;
}

export function ProtocolWorkspace({ projectId, list, tasks, canEdit, isOwner, h2Declaration, onChanged, studyType }: Props) {
    const versions = list?.items ?? [];
    const latest = versions[0];
    const frozen = versions.find((v) => v.status === "frozen");
    const sections = (list?.required_sections ?? []).filter((s) => s !== "ethics_rights_declaration");
    const [draft, setDraft] = useState<Record<string, string>>({});
    const [ethics, setEthics] = useState<EthicsRights>(EMPTY_ETHICS);
    const [compute, setCompute] = useState("");
    const [cost, setCost] = useState("");
    const [amendment, setAmendment] = useState("");
    const [afterInspection, setAfterInspection] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [waive, setWaive] = useState<ProtocolEntry | null>(null);
    const [resolve, setResolve] = useState<{ p: ProtocolEntry; index: number } | null>(null);
    const [freezeResult, setFreezeResult] = useState<string>();

    useEffect(() => {
        if (!latest) return;
        setDraft(latest.sections);
        setEthics(latest.ethics_rights ?? EMPTY_ETHICS);
        setCompute(latest.compute_estimate ?? "");
        setCost(latest.cost_estimate_cents != null ? String(latest.cost_estimate_cents / 100) : "");
    }, [latest?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const save = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/protocols`, {
                sections: Object.fromEntries(sections.map((s) => [s, draft[s] ?? ""])),
                ethics_rights: ethics,
                compute_estimate: compute || null,
                cost_estimate_cents: cost.trim() ? Math.round(Number(cost) * 100) : null,
                amendment_rationale: frozen ? amendment.trim() || null : null,
                after_data_inspection: frozen ? afterInspection : false,
            });
            setAmendment("");
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    const reviewTasks = tasks.filter((t) => t.kind === "methodology_review");

    return (
        <div className="flex flex-col gap-10">
            {canEdit && (
                <Section
                    title={frozen ? "Amend the frozen protocol" : "Draft the protocol"}
                    description={
                        frozen
                            ? `Protocol v${frozen.version} is frozen (H2). A change is a dated amendment with a rationale; freezing it invalidates results and stages bound to the old hash.`
                            : "Each version is saved as an immutable artifact. Required sections come from the selected method definition."
                    }
                >
                    <div className="flex flex-col gap-3">
                        {sections.map((s) =>
                            s === SPEC_SECTION && isReviewStudyType(studyType) ? (
                                <ReviewSpecEditor
                                    key={`${s}:${latest?.id ?? "new"}`}
                                    studyType={studyType}
                                    value={draft[s]}
                                    onChange={(v) => setDraft((d) => ({ ...d, [s]: v }))}
                                />
                            ) : (
                                <TextArea key={s} label={humanize(s)} value={draft[s] ?? ""} onChange={(v) => setDraft((d) => ({ ...d, [s]: v }))} rows={3} />
                            ),
                        )}
                        <EthicsForm value={ethics} onChange={setEthics} declarationText={latest?.ethics_declaration_text} />
                        <div className="grid gap-3 sm:grid-cols-2">
                            <Input label="Compute estimate" value={compute} onChange={setCompute} />
                            <Input label="Estimated platform cost (in project currency)" value={cost} onChange={setCost} inputMode="decimal" />
                        </div>
                        {frozen && (
                            <>
                                <TextArea label="Amendment rationale" isRequired hint="At least 20 characters." value={amendment} onChange={setAmendment} rows={2} />
                                <Checkbox isSelected={afterInspection} onChange={setAfterInspection} label="This amendment is made after inspecting the data" />
                            </>
                        )}
                        <ErrorAlert error={error} />
                        <div>
                            <Button size="sm" isLoading={busy} onClick={save}>
                                {frozen ? "Save amendment as a new version" : "Save protocol version"}
                            </Button>
                        </div>
                    </div>
                </Section>
            )}
            <TaskProgress tasks={reviewTasks} title="Independent methodology review" />
            <Section title="Protocol versions" description="Newest first. The H2 signature binds the exact version hash.">
                {versions.length === 0 && <p className="text-sm text-tertiary">No protocol saved yet.</p>}
                <ul className="flex flex-col gap-4">
                    {versions.map((p) => (
                        <ProtocolCard
                            key={p.id}
                            p={p}
                            projectId={projectId}
                            canEdit={canEdit}
                            isOwner={isOwner}
                            onChanged={onChanged}
                            onWaive={() => setWaive(p)}
                            onResolve={(index) => setResolve({ p, index })}
                        />
                    ))}
                </ul>
            </Section>
            {isOwner && latest && latest.status === "draft" && (
                <ApprovalPanel
                    gate="H2"
                    title={`Freeze protocol v${latest.version}`}
                    declaration={h2Declaration ?? list?.declaration ?? ""}
                    blockingReasons={h2BlockingReasons(latest.validation)}
                    submitLabel={`Sign H2 and freeze v${latest.version}`}
                    onSubmit={async (b) => {
                        const r = await api.post<{ frozen_hash: string }>(`/v1/projects/${projectId}/protocols/${latest.version}/approve`, b);
                        setFreezeResult(r.frozen_hash);
                        onChanged();
                    }}
                />
            )}
            {freezeResult && (
                <p data-testid="frozen-hash" className="text-sm text-success-primary">
                    Frozen. Results must name this protocol hash: <code className="break-all">{freezeResult}</code>
                </p>
            )}
            <WaiveDialog projectId={projectId} protocol={waive} onClose={() => setWaive(null)} onDone={onChanged} />
            <ResolveDialog projectId={projectId} target={resolve} onClose={() => setResolve(null)} onDone={onChanged} />
        </div>
    );
}

function ProtocolCard({
    p,
    projectId,
    canEdit,
    isOwner,
    onChanged,
    onWaive,
    onResolve,
}: {
    p: ProtocolEntry;
    projectId: string;
    canEdit: boolean;
    isOwner: boolean;
    onChanged: () => void;
    onWaive: () => void;
    onResolve: (index: number) => void;
}) {
    const [error, setError] = useState<unknown>();
    const [busy, setBusy] = useState(false);
    const v = p.validation;
    return (
        <li data-testid="protocol-version" data-status={p.status} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-primary">Protocol v{p.version}</span>
                <StatusBadge status={`protocol_${p.status}`} />
                {p.is_amendment && <span className="text-xs text-tertiary">Amendment{p.after_data_inspection ? " made after data inspection" : ""}</span>}
                {p.review_status && <StatusBadge status={`review_${p.review_status}`} />}
                <span className="text-xs text-tertiary">
                    hash {p.content_hash.slice(0, 16)} · {formatDateTime(p.created_at)}
                </span>
            </div>
            {p.amendment_rationale && <p className="text-sm text-secondary">Amendment rationale: {p.amendment_rationale}</p>}
            {p.frozen_at && <p className="text-xs text-tertiary">Frozen {formatDateTime(p.frozen_at)}</p>}
            {p.review_waiver_rationale && <p className="text-sm text-warning-primary">Review waived: {p.review_waiver_rationale}</p>}
            {v && p.status === "draft" && h2BlockingReasons(v).length > 0 && (
                <ul className="list-disc pl-5 text-sm text-tertiary" aria-label={`Open items for protocol v${p.version}`}>
                    {h2BlockingReasons(v).map((r) => (
                        <li key={r}>{r}</li>
                    ))}
                </ul>
            )}
            {v?.ready_for_h2 && p.status === "draft" && <p className="text-sm text-success-primary">Ready for H2.</p>}
            {p.review_issues.length > 0 && (
                <div className="flex flex-col gap-2">
                    <p className="text-sm font-medium text-secondary">
                        Review issues <span className="text-xs font-normal text-tertiary">(model-assisted independent review; advisory, not a human review)</span>
                    </p>
                    <ul className="flex flex-col gap-2">
                        {p.review_issues.map((i: ReviewIssue, idx: number) => (
                            <li key={idx} data-testid="review-issue" data-severity={i.severity} className="rounded-lg bg-secondary p-3 text-sm">
                                <span className={i.severity === "blocker" ? "font-semibold text-error-primary" : "font-semibold text-secondary"}>{humanize(i.severity)}</span>
                                <span className="text-tertiary"> · {humanize(i.section)}</span>
                                <p className="text-primary">{i.issue}</p>
                                <p className="text-xs text-tertiary">Why: {i.rationale}</p>
                                <p className="text-xs text-tertiary">Proposed fix: {i.proposed_fix}</p>
                                {i.resolved ? (
                                    <p className="text-xs text-success-primary">
                                        Resolved ({humanize(i.resolved)}): {i.resolution_note}
                                    </p>
                                ) : (
                                    isOwner &&
                                    p.status === "draft" && (
                                        <Button size="sm" color="secondary" className="mt-1" onClick={() => onResolve(idx)}>
                                            Resolve
                                        </Button>
                                    )
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <ErrorAlert error={error} />
            {p.status === "draft" && (
                <div className="flex flex-wrap gap-2">
                    {canEdit && p.review_status !== "requested" && (
                        <Button
                            size="sm"
                            color="secondary"
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    await api.post(`/v1/projects/${projectId}/protocols/${p.version}/review`, {});
                                    onChanged();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Request independent review
                        </Button>
                    )}
                    {isOwner && p.review_status !== "performed" && p.review_status !== "waived" && (
                        <Button size="sm" color="secondary" onClick={onWaive}>
                            Record a review waiver
                        </Button>
                    )}
                </div>
            )}
        </li>
    );
}

function WaiveDialog({ projectId, protocol, onClose, onDone }: { projectId: string; protocol: ProtocolEntry | null; onClose: () => void; onDone: () => void }) {
    const [rationale, setRationale] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <DialogShell
            isOpen={protocol !== null}
            onOpenChange={(o) => !o && onClose()}
            title="Record that independent review was not performed"
            description="The waiver and its rationale are shown at H2 and H4. It is not a review."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        isLoading={busy}
                        isDisabled={rationale.trim().length < 30}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(`/v1/projects/${projectId}/protocols/${protocol!.version}/waive-review`, { rationale });
                                setRationale("");
                                onClose();
                                onDone();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Record waiver
                    </Button>
                </>
            }
        >
            <TextArea label="Why no independent review" hint="At least 30 characters." value={rationale} onChange={setRationale} rows={3} />
            <ErrorAlert error={error} />
        </DialogShell>
    );
}

function ResolveDialog({ projectId, target, onClose, onDone }: { projectId: string; target: { p: ProtocolEntry; index: number } | null; onClose: () => void; onDone: () => void }) {
    const [resolution, setResolution] = useState("fixed");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const issue = target ? target.p.review_issues[target.index] : null;
    return (
        <DialogShell
            isOpen={target !== null}
            onOpenChange={(o) => !o && onClose()}
            title="Resolve a review issue"
            description={issue ? `${humanize(issue.severity)}: ${issue.issue}` : undefined}
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        isLoading={busy}
                        isDisabled={note.trim().length < 5}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(`/v1/projects/${projectId}/protocols/${target!.p.version}/issues/resolve`, { index: target!.index, resolution, note });
                                setNote("");
                                onClose();
                                onDone();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Record resolution
                    </Button>
                </>
            }
        >
            <NativeSelect
                label="Resolution"
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                options={[
                    { label: "Fixed in the protocol", value: "fixed" },
                    { label: "Accepted risk", value: "accepted_risk" },
                    { label: "Rejected with reason", value: "rejected_with_reason" },
                ]}
            />
            <TextArea label="Note" value={note} onChange={setNote} rows={3} />
            <ErrorAlert error={error} />
        </DialogShell>
    );
}
