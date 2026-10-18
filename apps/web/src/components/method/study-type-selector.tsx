"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { studyTypeTitle } from "@/components/opportunities/opportunity-card";
import { ErrorAlert } from "@/components/research/error-alert";
import { Field, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { MethodInstance, OpportunityEntry, StudyTypeTaxonomy } from "@/lib/api/types";
import { humanize } from "@/lib/format";

interface Props {
    projectId: string;
    instance: MethodInstance | null;
    taxonomy: StudyTypeTaxonomy | undefined;
    opportunities: OpportunityEntry[];
    isOwner: boolean;
    onChanged: () => void;
}

/**
 * Study type (what kind of research) and venue submission category (what kind of submission) are separate choices.
 * A switch creates a new method instance; the API invalidates H1 and everything downstream and never carries H2/H3.
 */
export function StudyTypeSelector({ projectId, instance, taxonomy, opportunities, isOwner, onChanged }: Props) {
    const [studyType, setStudyType] = useState(instance?.study_type ?? "");
    const [venue, setVenue] = useState(instance?.venue_category ?? "");
    const [opp, setOpp] = useState("");
    const [rationale, setRationale] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [result, setResult] = useState<MethodInstance>();

    const selected = taxonomy?.taxonomy.find((t) => t.study_type === studyType);
    const isSwitch = !!instance && (instance.study_type !== studyType || instance.venue_category !== venue);

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const r = await api.post<MethodInstance>(`/v1/projects/${projectId}/study-type/select`, {
                study_type: studyType,
                venue_category: venue,
                opportunity_id: opp || null,
                rationale: rationale.trim() || null,
            });
            setResult(r);
            setRationale("");
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <Section title="Study type and venue category" description={taxonomy?.note ?? "Study type and venue category are separate choices."}>
            {instance ? (
                <dl data-testid="method-instance" className="grid gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary sm:grid-cols-3">
                    <Field label="Study type">
                        <span className="flex flex-wrap items-center gap-2">
                            {instance.title}
                            <StatusBadge status={instance.enabled_for_submission_ready ? "method_enabled" : "method_planning_only"} />
                        </span>
                    </Field>
                    <Field label="Venue submission category">{humanize(instance.venue_category)}</Field>
                    <Field label="Track accepts this category">{instance.track_accepts}</Field>
                    {instance.planning_only_reason && (
                        <p className="text-sm text-warning-primary sm:col-span-3">Planning only: {instance.planning_only_reason}</p>
                    )}
                    {instance.selection_rationale && <p className="text-sm text-secondary sm:col-span-3">Your rationale: {instance.selection_rationale}</p>}
                    {instance.override_of_recommendation && (
                        <p className="text-xs text-tertiary sm:col-span-3">This choice differs from the advisory recommendation; your rationale is recorded.</p>
                    )}
                </dl>
            ) : (
                <p className="text-sm text-tertiary">No study type selected yet. H1 cannot be recorded until you choose one.</p>
            )}
            {(result?.reuse_decisions ?? instance?.reuse_decisions ?? []).length > 0 && (
                <div className="rounded-xl bg-secondary p-3">
                    <p className="text-sm font-medium text-secondary">What carried over from the previous method</p>
                    <ul className="mt-1 list-disc pl-5 text-sm text-tertiary">
                        {(result?.reuse_decisions ?? instance?.reuse_decisions ?? []).map((d) => (
                            <li key={d.item}>
                                {d.item}: {humanize(d.decision)} — {d.reason}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {(result?.switch_effects?.effects ?? []).length > 0 && (
                <ul className="list-disc pl-5 text-sm text-warning-primary">
                    {result!.switch_effects!.effects!.map((e) => (
                        <li key={e}>{e}</li>
                    ))}
                </ul>
            )}
            {isOwner && taxonomy && (
                <div className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
                    <div className="grid gap-3 sm:grid-cols-2">
                        <NativeSelect
                            label="Study type"
                            value={studyType}
                            onChange={(e) => setStudyType(e.target.value)}
                            options={[
                                { label: "Choose a study type", value: "" },
                                ...taxonomy.taxonomy.map((t) => ({
                                    label: `${t.title || studyTypeTitle(t.study_type)}${t.enabled_for_submission_ready ? "" : " (planning only)"}`,
                                    value: t.study_type,
                                })),
                            ]}
                        />
                        <NativeSelect
                            label="Venue submission category"
                            value={venue}
                            onChange={(e) => setVenue(e.target.value)}
                            options={[{ label: "Choose a category", value: "" }, ...Object.keys(taxonomy.venue_categories).map((k) => ({ label: humanize(k), value: k }))]}
                        />
                    </div>
                    {selected && <p className="text-sm text-tertiary">{selected.definition}</p>}
                    {selected && !selected.enabled_for_submission_ready && (
                        <p className="text-sm text-warning-primary">Planning only: {selected.planning_only_reason ?? "this study type cannot be labelled submission-ready in this release."}</p>
                    )}
                    {opportunities.length > 0 && (
                        <NativeSelect
                            label="Proposal this choice relates to (optional)"
                            value={opp}
                            onChange={(e) => setOpp(e.target.value)}
                            options={[{ label: "None", value: "" }, ...opportunities.map((o) => ({ label: o.title, value: o.id }))]}
                        />
                    )}
                    <TextArea
                        label="Rationale"
                        hint="Required (at least 20 characters) when the choice differs from the advice or the track's acceptance of this category is unknown."
                        value={rationale}
                        onChange={setRationale}
                        rows={2}
                    />
                    {isSwitch && (
                        <p className="text-sm text-warning-primary">
                            Switching the method creates a new method workflow. H1 and everything downstream must be decided again; prior H2/H3 approvals never transfer.
                        </p>
                    )}
                    <ErrorAlert error={error} />
                    <div>
                        <Button size="sm" isLoading={busy} isDisabled={!studyType || !venue} onClick={submit}>
                            {instance ? "Change study type or category" : "Select study type"}
                        </Button>
                    </div>
                </div>
            )}
        </Section>
    );
}
