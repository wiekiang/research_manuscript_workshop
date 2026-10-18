"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { FixtureNotice } from "@/components/research/verification-method-label";
import { api } from "@/lib/api/client";
import type { CandidateDetail, GenerationCandidate, ManuscriptVersion, SectionDiff } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";
import { type ApplyRefusal, candidateAction, candidateStatusKey, interpretConflict } from "@/lib/manuscript";

interface Props {
    manuscriptId: string;
    candidates: GenerationCandidate[];
    currentVersionId: string;
    currentVersion: number;
    canEdit: boolean;
    onChanged: () => void;
}

export function DiffView({ diffs }: { diffs: SectionDiff[] }) {
    if (diffs.length === 0) return <p className="text-sm text-tertiary">No text differences from the current version.</p>;
    return (
        <div className="flex flex-col gap-3" data-testid="candidate-diff">
            {diffs.map((d) => (
                <div key={d.section}>
                    <p className="text-sm font-medium text-secondary">{humanize(d.section)}</p>
                    <pre className="max-h-64 overflow-auto rounded-lg bg-secondary p-3 text-xs whitespace-pre-wrap text-secondary">
                        {d.diff.split("\n").map((line, i) => (
                            <span key={i} className={line.startsWith("+") && !line.startsWith("+++") ? "text-success-primary" : line.startsWith("-") && !line.startsWith("---") ? "text-error-primary" : undefined}>
                                {line}
                                {"\n"}
                            </span>
                        ))}
                    </pre>
                </div>
            ))}
        </div>
    );
}

/** Generated drafts. A candidate never replaces the manuscript silently: apply only when current, otherwise merge. */
export function CandidatesPanel({ manuscriptId, candidates, currentVersionId, currentVersion, canEdit, onChanged }: Props) {
    const [openId, setOpenId] = useState<string | null>(null);
    return (
        <Section title="Generated drafts" description="Each draft is generated against a frozen manuscript version and the frozen brief. Review the diff before applying or merging.">
            {candidates.length === 0 && <p className="text-sm text-tertiary">No drafts generated yet.</p>}
            <ul className="flex flex-col gap-2">
                {candidates.map((c) => {
                    const action = candidateAction(c, currentVersionId);
                    return (
                        <li key={c.id} data-testid="candidate-row" data-status={c.status} className="flex flex-wrap items-center gap-2 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                            <StatusBadge status={candidateStatusKey(c.status)} />
                            <span className="text-sm text-primary">{c.sections.map(humanize).join(", ")}</span>
                            <span className="text-xs text-tertiary">{formatDateTime(c.created_at)}</span>
                            {c.conflicts.some((x) => x.error) && <span className="text-xs text-error-primary">{c.conflicts.find((x) => x.error)?.error}</span>}
                            {c.artifact_id && (
                                <Button size="sm" color="secondary" className="ml-auto" onClick={() => setOpenId(c.id)}>
                                    {canEdit && action === "apply" ? "Review and apply" : canEdit && action === "merge" ? "Review and merge" : "View"}
                                </Button>
                            )}
                        </li>
                    );
                })}
            </ul>
            <CandidateDialog
                manuscriptId={manuscriptId}
                candidateId={openId}
                currentVersion={currentVersion}
                canEdit={canEdit}
                onClose={() => setOpenId(null)}
                onChanged={onChanged}
            />
        </Section>
    );
}

function CandidateDialog({
    manuscriptId,
    candidateId,
    currentVersion,
    canEdit,
    onClose,
    onChanged,
}: {
    manuscriptId: string;
    candidateId: string | null;
    currentVersion: number;
    canEdit: boolean;
    onClose: () => void;
    onChanged: () => void;
}) {
    const [detail, setDetail] = useState<CandidateDetail>();
    const [loadError, setLoadError] = useState<unknown>();
    const [take, setTake] = useState<string[]>([]);
    const [refusal, setRefusal] = useState<ApplyRefusal | null>(null);
    const [error, setError] = useState<unknown>();
    const [busy, setBusy] = useState(false);
    const [merged, setMerged] = useState<(ManuscriptVersion & { conflicts?: { section?: string; kept_protected_spans?: string[]; note?: string }[] }) | null>(null);
    const [mode, setMode] = useState<"review" | "merge">("review");

    const load = async (id: string) => {
        setLoadError(undefined);
        try {
            const d = await api.get<CandidateDetail>(`/v1/manuscripts/${manuscriptId}/candidates/${id}`);
            setDetail(d);
            setTake(d.sections);
            setMode(d.is_stale ? "merge" : "review");
        } catch (err) {
            setLoadError(err);
        }
    };

    useEffect(() => {
        setDetail(undefined);
        setRefusal(null);
        setError(undefined);
        setMerged(null);
        if (candidateId) void load(candidateId);
    }, [candidateId]); // eslint-disable-line react-hooks/exhaustive-deps

    const actionable = detail && ["ready", "stale"].includes(detail.status);
    const providers = (detail?.provenance.sections ?? []).map((p) => p.provider);
    const validation = (detail?.rationale?._validation_problems as string[] | undefined) ?? [];

    const apply = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/manuscripts/${manuscriptId}/candidates/${candidateId}/apply`, {});
            onChanged();
            onClose();
        } catch (err) {
            const r = interpretConflict(err);
            if (r) {
                setRefusal(r);
                setMode("merge");
                onChanged();
            } else setError(err);
        } finally {
            setBusy(false);
        }
    };

    const merge = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const v = await api.post<ManuscriptVersion & { conflicts: { section?: string; kept_protected_spans?: string[]; note?: string }[] }>(
                `/v1/manuscripts/${manuscriptId}/candidates/${candidateId}/merge`,
                { expected_version: currentVersion, take_candidate_sections: take },
            );
            setMerged(v);
            onChanged();
        } catch (err) {
            const r = interpretConflict(err);
            if (r) setRefusal(r);
            else setError(err);
        } finally {
            setBusy(false);
        }
    };

    const reject = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/manuscripts/${manuscriptId}/candidates/${candidateId}/reject`, {});
            onChanged();
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <DialogShell
            isOpen={candidateId !== null}
            onOpenChange={(o) => !o && onClose()}
            size="lg"
            title="Generated draft"
            description={detail ? `Sections: ${detail.sections.map(humanize).join(", ")}` : undefined}
            footer={
                merged ? (
                    <Button onClick={onClose}>Done</Button>
                ) : canEdit && actionable ? (
                    <>
                        <Button color="secondary-destructive" isDisabled={busy} onClick={reject}>
                            Reject draft
                        </Button>
                        {mode === "review" ? (
                            <Button isLoading={busy} onClick={apply}>
                                Apply as a new version
                            </Button>
                        ) : (
                            <Button isLoading={busy} isDisabled={take.length === 0} onClick={merge}>
                                Merge selected sections into v{currentVersion}
                            </Button>
                        )}
                    </>
                ) : (
                    <Button color="secondary" onClick={onClose}>
                        Close
                    </Button>
                )
            }
        >
            <div data-testid="candidate-dialog" className="flex max-h-[65vh] flex-col gap-4 overflow-y-auto pr-1">
                <ErrorAlert error={loadError} />
                {!detail && !loadError && <Loading label="Loading draft" />}
                {detail && (
                    <>
                        <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={candidateStatusKey(detail.is_stale && detail.status === "ready" ? "stale" : detail.status)} />
                            <span className="text-xs text-tertiary">AI-drafted by the section writer agent</span>
                        </div>
                        {providers.includes("fixture") && <FixtureNotice provider="fixture" />}
                        {detail.is_stale && (
                            <p role="status" data-testid="stale-candidate-notice" className="rounded-xl bg-warning-primary p-3 text-sm text-secondary">
                                The manuscript changed while this draft was generated. It cannot be applied over the current text; choose the sections to merge into version {currentVersion}. Human-authored sentences are always kept.
                            </p>
                        )}
                        {refusal && (
                            <p role="alert" data-testid="apply-refusal" data-code={refusal.kind} className="rounded-xl bg-warning-primary p-3 text-sm text-secondary">
                                {refusal.message}
                                {refusal.sections.length > 0 && ` Sections with human-authored text: ${refusal.sections.map(humanize).join(", ")}.`} Choose what to merge below.
                            </p>
                        )}
                        {merged && (
                            <div data-testid="merge-result" className="flex flex-col gap-1 rounded-xl bg-success-primary p-3 text-sm text-secondary">
                                <p>Merged into new version {merged.version}.</p>
                                {(merged.conflicts ?? []).map((c, i) => (
                                    <p key={i}>
                                        {humanize(c.section ?? "")}: {c.note} ({(c.kept_protected_spans ?? []).length} human sentence(s) kept)
                                    </p>
                                ))}
                            </div>
                        )}
                        {validation.length > 0 && (
                            <div>
                                <p className="text-sm font-medium text-secondary">Validation of the agent output</p>
                                <ul className="list-disc pl-5 text-xs text-tertiary">
                                    {validation.map((v) => (
                                        <li key={v}>{v}</li>
                                    ))}
                                </ul>
                            </div>
                        )}
                        {Object.entries(detail.rationale)
                            .filter(([k]) => !k.startsWith("_"))
                            .map(([k, v]) => {
                                const r = v as { rationale?: string; open_questions?: string[] };
                                return (
                                    <div key={k} className="text-sm">
                                        <p className="font-medium text-secondary">{humanize(k)}: why this draft</p>
                                        <p className="text-tertiary">{r.rationale}</p>
                                        {(r.open_questions ?? []).length > 0 && <p className="text-xs text-tertiary">Open questions: {r.open_questions!.join("; ")}</p>}
                                    </div>
                                );
                            })}
                        {mode === "merge" && canEdit && actionable && !merged && (
                            <fieldset className="flex flex-col gap-1">
                                <legend className="text-sm font-medium text-secondary">Take these sections from the draft</legend>
                                {detail.sections.map((s) => (
                                    <Checkbox key={s} isSelected={take.includes(s)} onChange={(v) => setTake((t) => (v ? [...t, s] : t.filter((x) => x !== s)))} label={humanize(s)} />
                                ))}
                            </fieldset>
                        )}
                        <p className="text-sm font-medium text-secondary">Changes compared with the current version</p>
                        <DiffView diffs={refusal?.diff.length ? refusal.diff : detail.diff_vs_current} />
                        <ErrorAlert error={error} />
                    </>
                )}
            </div>
        </DialogShell>
    );
}
