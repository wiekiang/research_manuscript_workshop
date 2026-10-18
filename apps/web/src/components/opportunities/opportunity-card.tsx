"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TextArea } from "@/components/base/textarea/textarea";
import { IdentityBadge } from "@/components/literature/papers-panel";
import { ErrorAlert } from "@/components/research/error-alert";
import { Field } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { VerificationMethodLabel } from "@/components/research/verification-method-label";
import { api } from "@/lib/api/client";
import type { FeasibilityEntry, OpportunityEntry, RationaleEntry, StudyTypeRec } from "@/lib/api/types";
import { formatInStatedZone, formatUtc } from "@/lib/format";
import { FEASIBILITY_STATUS, TRACK_ACCEPTS } from "@/lib/literature";

const STUDY_TITLE: Record<string, string> = {
    empirical_quantitative: "Primary empirical quantitative study",
    secondary_data: "Secondary data analysis",
    empirical_qualitative: "Primary empirical qualitative study",
    theoretical: "Theoretical contribution",
    methodological: "Methodological contribution",
    narrative_review: "Narrative literature review",
    systematic_review: "Systematic review",
    meta_analysis: "Meta-analysis",
    mapping_review: "Mapping study",
    scoping_review: "Scoping review",
    tertiary_review: "Tertiary review",
    computational_experiment: "Platform-executed computational study",
};

export function studyTypeTitle(key: string): string {
    return STUDY_TITLE[key] ?? key.replace(/_/g, " ");
}

/** Study type (what kind of research) and venue category (what kind of submission) are separate fields. */
export function StudyTypeRecommendation({ rec }: { rec: StudyTypeRec }) {
    return (
        <li data-testid="study-type-rec" className="flex flex-col gap-2 rounded-lg bg-secondary p-3">
            <dl className="grid gap-2 sm:grid-cols-2">
                <Field label="Study type (research method)">
                    <span data-testid="rec-study-type">{studyTypeTitle(rec.study_type)}</span>
                </Field>
                <Field label="Venue submission category">
                    <span data-testid="rec-venue-category">{rec.venue_category.replace(/_/g, " ")}</span>
                </Field>
            </dl>
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge
                    status={rec.method_enabled ? "complete" : "not_performed"}
                    label={rec.method_enabled ? "Method enabled for submission-ready output" : "Planning only in this release"}
                />
                <span className="text-xs text-tertiary">{rec.method_availability}</span>
                <span className="text-xs text-secondary">· {TRACK_ACCEPTS[rec.track_accepts] ?? rec.track_accepts}</span>
            </div>
            <p className="text-sm text-secondary">{rec.fit_rationale}</p>
            {rec.reporting_standard && <p className="text-xs text-tertiary">Reporting standard: {rec.reporting_standard}</p>}
            {rec.required_inputs.length > 0 && <p className="text-xs text-tertiary">Required inputs: {rec.required_inputs.join(", ")}</p>}
            {rec.blockers.length > 0 && (
                <ul className="list-disc pl-5 text-xs text-warning-primary">
                    {rec.blockers.map((b) => (
                        <li key={b}>{b}</li>
                    ))}
                </ul>
            )}
            <p className="text-xs text-tertiary">Advisory recommendation; you choose the study type and venue category at H1.</p>
        </li>
    );
}

export function FeasibilityPanel({ f }: { f: FeasibilityEntry }) {
    const spec = FEASIBILITY_STATUS[f.status] ?? { label: f.status, status: "not_performed" };
    return (
        <div data-testid="feasibility" className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={spec.status} label={spec.label} />
                <span className="text-xs text-tertiary">
                    version {f.version}
                    {f.slack_days != null ? ` · slack ${f.slack_days} days` : ""}
                </span>
            </div>
            <p className="text-sm text-secondary">{f.uncertainty}</p>
            <ul className="text-sm text-tertiary">
                {f.deadlines.length === 0 && <li>No official submission deadline with a timezone is recorded for the target track.</li>}
                {f.deadlines.map((d) => (
                    <li key={d.kind}>
                        {d.kind.replace(/_/g, " ")}: {formatUtc(d.due_at)}
                        {d.stated_timezone && formatInStatedZone(d.due_at, d.stated_timezone) ? ` (${formatInStatedZone(d.due_at, d.stated_timezone)})` : ""} · {d.status}
                    </li>
                ))}
            </ul>
            <p className="text-xs text-tertiary">
                Estimates: research {f.estimates.research_weeks?.join("–") ?? "?"} weeks, writing {f.estimates.writing_weeks ?? "?"} weeks, validation {f.estimates.validation_weeks ?? "?"} weeks (
                {f.estimates.source ?? "unknown source"}).
            </p>
            {f.constraints.length > 0 && <p className="text-xs text-tertiary">Constraints: {f.constraints.join("; ")}</p>}
            {f.assumptions.length > 0 && <p className="text-xs text-tertiary">Assumptions: {f.assumptions.join("; ")}</p>}
            {f.cost_estimate?.note && <p className="text-xs text-tertiary">Cost: {f.cost_estimate.note}</p>}
            <p className="text-xs text-secondary">{f.note}</p>
        </div>
    );
}

const RATIONALE_FIELDS: { key: keyof RationaleEntry; label: string }[] = [
    { key: "problem", label: "Practical or scientific problem" },
    { key: "gap", label: "Specific gap or unresolved disagreement" },
    { key: "importance_to_venue", label: "Why it matters to the chosen venue" },
    { key: "research_question", label: "Proposed research question" },
    { key: "intended_contribution", label: "Intended contribution" },
    { key: "success_criterion", label: "What result would count as addressing the gap" },
];

export function RationalePanel({ projectId, r, canEdit, onChanged }: { projectId: string; r: RationaleEntry; canEdit: boolean; onChanged: () => void }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState<Record<string, string>>({});
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <section aria-label="Why this paper?" data-testid="rationale" className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <h4 className="font-display text-md font-semibold text-primary">Why this paper?</h4>
                <StatusBadge status={r.status} />
                <span className="text-xs text-tertiary">Paper Rationale v{r.version}</span>
            </div>
            <p className="text-xs font-medium text-warning-primary">{r.label}</p>
            {!editing ? (
                <dl className="grid gap-3 sm:grid-cols-2">
                    {RATIONALE_FIELDS.map((f) => (
                        <Field key={f.key} label={f.label}>
                            {String(r[f.key] ?? "") || <span className="text-tertiary">—</span>}
                        </Field>
                    ))}
                </dl>
            ) : (
                <div className="flex flex-col gap-3">
                    {RATIONALE_FIELDS.map((f) => (
                        <TextArea key={f.key} label={f.label} value={draft[f.key] ?? String(r[f.key] ?? "")} onChange={(v) => setDraft((d) => ({ ...d, [f.key]: v }))} rows={2} />
                    ))}
                </div>
            )}
            <div>
                <p className="text-xs font-medium text-secondary">Source-backed evidence that the gap exists</p>
                {r.gap_evidence.length === 0 ? (
                    <p className="text-xs text-warning-primary">No verified passage is linked yet. Link evidence from the evidence workspace before relying on this gap.</p>
                ) : (
                    <ul className="flex flex-col gap-1">
                        {r.gap_evidence.map((g) => (
                            <li key={g.passage_id} className="border-l-2 border-brand pl-3 text-sm text-secondary italic">
                                “{g.quote}”
                            </li>
                        ))}
                    </ul>
                )}
            </div>
            <ErrorAlert error={error} />
            {canEdit && (
                <div className="flex gap-2">
                    {!editing ? (
                        <Button size="sm" color="secondary" onClick={() => setEditing(true)}>
                            Edit rationale
                        </Button>
                    ) : (
                        <>
                            <Button
                                size="sm"
                                isLoading={busy}
                                onClick={async () => {
                                    setBusy(true);
                                    setError(undefined);
                                    try {
                                        await api.patch(`/v1/projects/${projectId}/rationales/${r.id}`, draft);
                                        setEditing(false);
                                        setDraft({});
                                        onChanged();
                                    } catch (err) {
                                        setError(err);
                                    } finally {
                                        setBusy(false);
                                    }
                                }}
                            >
                                Save as new version
                            </Button>
                            <Button size="sm" color="secondary" onClick={() => { setEditing(false); setDraft({}); }}>
                                Cancel
                            </Button>
                        </>
                    )}
                </div>
            )}
        </section>
    );
}

export function OpportunityCard({ projectId, o, canEdit, onChanged }: { projectId: string; o: OpportunityEntry; canEdit: boolean; onChanged: () => void }) {
    const d = o.details;
    return (
        <article data-testid="opportunity" aria-labelledby={`opp-${o.id}`} className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                    <h3 id={`opp-${o.id}`} className="font-display text-lg font-semibold text-primary">
                        {o.position}. {o.title}
                    </h3>
                    <StatusBadge status={o.status} />
                    {o.provenance?.provider && <VerificationMethodLabel method="model_assisted" provider={o.provenance.provider} />}
                </div>
                <p className="text-md text-secondary">{o.research_question}</p>
            </div>
            <dl className="grid gap-3 sm:grid-cols-2">
                <Field label="CFP alignment">{d.cfp_alignment ?? "—"}</Field>
                <Field label="Potential contribution">{d.potential_contribution ?? "—"}</Field>
                <Field label="How it differs from prior work">{d.how_it_differs ?? "—"}</Field>
                <Field label="Boundary conditions">{d.boundary_conditions ?? "—"}</Field>
                <Field label="Data availability">{d.data_availability ?? "—"}</Field>
                <Field label="Compute estimate">{d.compute_estimate ?? "—"}</Field>
                {d.ethics_constraints && <Field label="Ethics constraints">{d.ethics_constraints}</Field>}
            </dl>
            <div className="flex flex-col gap-2">
                <h4 className="text-sm font-semibold text-secondary">Closest prior work</h4>
                {o.closest_work.length === 0 ? (
                    <p className="text-sm text-tertiary">None identified.</p>
                ) : (
                    <ul className="flex flex-col gap-2">
                        {o.closest_work.map((w) => (
                            <li key={w.paper_id} className="flex flex-col gap-1">
                                <span className="text-sm text-primary">
                                    {w.title}
                                    {w.year ? ` (${w.year})` : ""}
                                    {w.doi ? ` · doi:${w.doi}` : ""}
                                </span>
                                <IdentityBadge paper={{ identity_status: w.identity_status, identity_verification: {} }} />
                            </li>
                        ))}
                    </ul>
                )}
            </div>
            <div className="flex flex-col gap-1 rounded-lg bg-warning-primary p-3">
                <p className="text-sm font-medium text-secondary">Novelty caveat: {o.novelty_caveat}</p>
                {(d.threats_to_novelty ?? []).length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-secondary">
                        {(d.threats_to_novelty ?? []).map((t) => (
                            <li key={t}>{t}</li>
                        ))}
                    </ul>
                )}
            </div>
            {o.rationale && <RationalePanel projectId={projectId} r={o.rationale} canEdit={canEdit} onChanged={onChanged} />}
            <div className="flex flex-col gap-2">
                <h4 className="text-sm font-semibold text-secondary">Study type and venue category recommendations</h4>
                <ul className="flex flex-col gap-2">
                    {o.study_types.map((r) => (
                        <StudyTypeRecommendation key={r.id} rec={r} />
                    ))}
                </ul>
            </div>
            {o.feasibility && (
                <div className="flex flex-col gap-2">
                    <h4 className="text-sm font-semibold text-secondary">Feasibility (advisory)</h4>
                    <FeasibilityPanel f={o.feasibility} />
                </div>
            )}
        </article>
    );
}
