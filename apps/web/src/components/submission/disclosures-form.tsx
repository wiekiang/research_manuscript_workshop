"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { Disclosures, DisclosuresView } from "@/lib/api/types";
import { DISCLOSURE_LIMITS, disclosureProblems, emptyDisclosures } from "@/lib/submission";

function initial(view: DisclosuresView): Disclosures {
    if (view.disclosures) return { ...emptyDisclosures(), ...view.disclosures };
    const d = emptyDisclosures();
    // Prefill only with the venue's own policy text from the confirmed CFP snapshot; never with invented text.
    if (view.venue_ai_policy_from_cfp?.quote) {
        d.ai_policy_text = view.venue_ai_policy_from_cfp.quote;
        d.ai_policy_source = `Official CFP snapshot (rule ${view.venue_ai_policy_from_cfp.rule_id})`;
    }
    return d;
}

/**
 * Disclosures and the venue AI-use policy. The policy text is the venue or publisher text as published; the
 * interpretation is the researcher's own reading. Saving invalidates H4 and packages bound to the previous version.
 */
export function DisclosuresForm({ view, projectId, canEdit, onSaved }: { view: DisclosuresView; projectId: string; canEdit: boolean; onSaved: () => void }) {
    const [d, setD] = useState<Disclosures>(() => initial(view));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [touched, setTouched] = useState(false);
    const problems = disclosureProblems(d);
    const set = (k: keyof Disclosures) => (v: string) => setD((x) => ({ ...x, [k]: v }));
    const L = DISCLOSURE_LIMITS;
    return (
        <form
            noValidate
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
                e.preventDefault();
                setTouched(true);
                if (problems.length) return;
                setBusy(true);
                setError(undefined);
                try {
                    await api.put(`/v1/projects/${projectId}/disclosures`, { expected_record_version: view.record_version, disclosures: d });
                    onSaved();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <div className="grid gap-3 sm:grid-cols-2">
                <TextArea label={L.competing_interests.label} isRequired value={d.competing_interests} onChange={set("competing_interests")} rows={2} />
                <TextArea label={L.funding.label} isRequired value={d.funding} onChange={set("funding")} rows={2} />
            </div>
            <TextArea label={L.ethics_statement.label} isRequired value={d.ethics_statement} onChange={set("ethics_statement")} rows={2} />
            <TextArea
                label={L.ai_use.label}
                hint={`The current manuscript version has ${view.ai_drafted_spans} AI-drafted sentence(s).`}
                isRequired
                value={d.ai_use}
                onChange={set("ai_use")}
                rows={3}
            />
            <TextArea label={L.ai_policy_text.label} hint="Paste the policy as published; do not paraphrase it." isRequired value={d.ai_policy_text} onChange={set("ai_policy_text")} rows={4} />
            <Input label={L.ai_policy_source.label} isRequired value={d.ai_policy_source} onChange={set("ai_policy_source")} />
            <TextArea label={L.ai_policy_interpretation.label} isRequired value={d.ai_policy_interpretation} onChange={set("ai_policy_interpretation")} rows={3} />
            <TextArea label="Data availability (optional)" value={d.data_availability ?? ""} onChange={(v) => setD((x) => ({ ...x, data_availability: v || null }))} rows={2} />
            {touched && problems.length > 0 && (
                <div role="alert" data-testid="disclosure-problems" className="rounded-xl border border-error_subtle bg-error-primary p-4">
                    <p className="text-sm font-semibold text-error-primary">Complete these fields before saving</p>
                    <ul className="mt-1 list-disc pl-5 text-sm text-secondary">
                        {problems.map((p) => (
                            <li key={p}>{p}</li>
                        ))}
                    </ul>
                </div>
            )}
            <ErrorAlert error={error} />
            {canEdit ? (
                <div>
                    <Button type="submit" size="sm" isLoading={busy}>
                        Save disclosures
                    </Button>
                </div>
            ) : (
                <p className="text-sm text-tertiary">Only the owner or a co-author can change the disclosures.</p>
            )}
        </form>
    );
}
