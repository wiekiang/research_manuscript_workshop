"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { ContributionEntry, QualWorkspace } from "@/lib/api/types";
import { Refusal } from "./refusal";

export const INTERPRETATION_MIN = 80;

function useSubmit(onDone: () => void) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const submit = async (path: string, body: object, reset: () => void) => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(path, body);
            reset();
            onDone();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };
    return { busy, error, submit };
}

interface Props {
    projectId: string;
    data: QualWorkspace;
    sources: ContributionEntry[];
    canEdit: boolean;
    onChanged: () => void;
}

/** Codebook, verbatim-verified coded segments and themes, with the source-to-code trace (audit trail). */
export function QualitativeWorkspace({ projectId, data, sources, canEdit, onChanged }: Props) {
    const [code, setCode] = useState({ code: "", definition: "" });
    const [seg, setSeg] = useState({ code_id: "", contribution_id: "", quote: "", memo: "" });
    const [theme, setTheme] = useState({ name: "", description: "", code_ids: [] as string[], interpretation: "" });
    const c = useSubmit(onChanged);
    const s = useSubmit(onChanged);
    const t = useSubmit(onChanged);
    const sourceTitle = (id: string) => sources.find((x) => x.id === id)?.title ?? id;
    const codeName = (id: string) => data.codes.find((x) => x.id === id)?.code ?? id;

    return (
        <div className="flex flex-col gap-10">
            <Section title="Codebook" description="Codes and their definitions. Every code needs at least one verbatim segment for the coding stage to validate.">
                {data.codes.length === 0 ? (
                    <p data-testid="qual-empty-codes" className="rounded-xl border border-dashed border-primary p-6 text-sm text-tertiary">
                        No codes yet. Coding happens under the H2-frozen protocol, after the ethics and collection stages.
                    </p>
                ) : (
                    <ul className="flex flex-col gap-2">
                        {data.codes.map((x) => (
                            <li key={x.id} data-testid="qual-code" className="rounded-xl bg-primary p-3 text-sm ring-1 ring-secondary">
                                <p className="font-medium text-primary">
                                    {x.code} <span className="text-xs font-normal text-tertiary">· {x.segments} segment(s)</span>
                                </p>
                                <p className="text-tertiary">{x.definition}</p>
                            </li>
                        ))}
                    </ul>
                )}
                {canEdit && (
                    <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary">
                        <Input label="Code" value={code.code} onChange={(v) => setCode((x) => ({ ...x, code: v }))} />
                        <TextArea label="Definition" value={code.definition} onChange={(v) => setCode((x) => ({ ...x, definition: v }))} rows={2} hint="At least 10 characters." />
                        <Refusal error={c.error} />
                        <div>
                            <Button
                                size="sm"
                                isLoading={c.busy}
                                isDisabled={code.code.trim().length < 2 || code.definition.trim().length < 10}
                                onClick={() => c.submit(`/v1/projects/${projectId}/qual/codes`, code, () => setCode({ code: "", definition: "" }))}
                            >
                                Add code
                            </Button>
                        </div>
                    </div>
                )}
            </Section>

            <Section title="Coded segments" description="Paste the excerpt exactly as it appears in the source; the platform checks it verbatim before saving.">
                {data.segments.length === 0 && <p className="text-sm text-tertiary">No coded segments yet.</p>}
                <ul className="flex flex-col gap-2">
                    {data.segments.map((x) => (
                        <li key={x.id} data-testid="qual-segment" className="flex flex-col gap-1 rounded-xl bg-primary p-3 text-sm ring-1 ring-secondary">
                            <p className="flex flex-wrap items-center gap-2">
                                <span className="font-medium text-primary">{codeName(x.code_id)}</span>
                                {x.verified && <StatusBadge status="segment_verified" />}
                                <span className="text-xs text-tertiary">from {sourceTitle(x.contribution_id)}</span>
                            </p>
                            <blockquote className="border-l-2 border-brand pl-3 text-secondary">“{x.quote}”</blockquote>
                            {x.memo && <p className="text-xs text-tertiary">Memo: {x.memo}</p>}
                        </li>
                    ))}
                </ul>
                {canEdit && data.codes.length > 0 && (
                    <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary">
                        <div className="grid gap-2 sm:grid-cols-2">
                            <NativeSelect
                                label="Code"
                                value={seg.code_id}
                                onChange={(e) => setSeg((x) => ({ ...x, code_id: e.target.value }))}
                                options={[{ label: "Select a code", value: "" }, ...data.codes.map((x) => ({ label: x.code, value: x.id }))]}
                            />
                            <NativeSelect
                                label="Source"
                                value={seg.contribution_id}
                                onChange={(e) => setSeg((x) => ({ ...x, contribution_id: e.target.value }))}
                                options={[{ label: "Select a source contribution", value: "" }, ...sources.map((x) => ({ label: `${x.title} (${x.type})`, value: x.id }))]}
                            />
                        </div>
                        <TextArea label="Quote (verbatim)" value={seg.quote} onChange={(v) => setSeg((x) => ({ ...x, quote: v }))} rows={3} />
                        <Input label="Memo (optional)" value={seg.memo} onChange={(v) => setSeg((x) => ({ ...x, memo: v }))} />
                        <Refusal error={s.error} />
                        <div>
                            <Button
                                size="sm"
                                isLoading={s.busy}
                                isDisabled={!seg.code_id || !seg.contribution_id || seg.quote.trim().length < 5}
                                onClick={() =>
                                    s.submit(`/v1/projects/${projectId}/qual/segments`, { ...seg, memo: seg.memo || null }, () => setSeg((x) => ({ ...x, quote: "", memo: "" })))
                                }
                            >
                                Add coded segment
                            </Button>
                        </div>
                    </div>
                )}
            </Section>

            <Section title="Themes" description="Each theme is built from codes with verbatim segments and carries your interpretation.">
                {data.themes.length === 0 && <p className="text-sm text-tertiary">No themes yet.</p>}
                {canEdit && data.codes.length > 0 && (
                    <div className="flex flex-col gap-2 rounded-xl p-4 ring-1 ring-secondary">
                        <Input label="Theme name" value={theme.name} onChange={(v) => setTheme((x) => ({ ...x, name: v }))} />
                        <TextArea label="Description" value={theme.description} onChange={(v) => setTheme((x) => ({ ...x, description: v }))} rows={2} />
                        <fieldset className="flex flex-col gap-1">
                            <legend className="text-sm font-medium text-secondary">Codes</legend>
                            {data.codes.map((x) => (
                                <Checkbox
                                    key={x.id}
                                    label={x.code}
                                    isSelected={theme.code_ids.includes(x.id)}
                                    onChange={(on) => setTheme((th) => ({ ...th, code_ids: on ? [...th.code_ids, x.id] : th.code_ids.filter((i) => i !== x.id) }))}
                                />
                            ))}
                        </fieldset>
                        <TextArea
                            label="Your interpretation"
                            value={theme.interpretation}
                            onChange={(v) => setTheme((x) => ({ ...x, interpretation: v }))}
                            rows={4}
                            hint={`${theme.interpretation.trim().length}/${INTERPRETATION_MIN} characters minimum. This is your reading, recorded in the contribution ledger.`}
                        />
                        <Refusal error={t.error} />
                        <div>
                            <Button
                                size="sm"
                                isLoading={t.busy}
                                isDisabled={
                                    theme.name.trim().length < 3 || theme.description.trim().length < 10 || theme.code_ids.length === 0 || theme.interpretation.trim().length < INTERPRETATION_MIN
                                }
                                onClick={() => t.submit(`/v1/projects/${projectId}/qual/themes`, theme, () => setTheme({ name: "", description: "", code_ids: [], interpretation: "" }))}
                            >
                                Add theme
                            </Button>
                        </div>
                    </div>
                )}
            </Section>

            <Section title="Source-to-code trace" description="Theme → code → verbatim excerpt → source, the audit trail the coding and analysis stages validate.">
                {data.themes.length === 0 ? (
                    <p className="text-sm text-tertiary">The trace appears once a theme exists.</p>
                ) : (
                    <ul className="flex flex-col gap-3" data-testid="qual-trace">
                        {data.themes.map((th) => (
                            <li key={th.id} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                                <p className="font-medium text-primary">{th.name}</p>
                                <p className="text-sm text-tertiary">{th.description}</p>
                                <p className="text-sm text-secondary">Interpretation: {th.interpretation}</p>
                                <ul className="flex flex-col gap-1 pl-3">
                                    {th.code_ids.map((cid) => {
                                        const segs = data.segments.filter((x) => x.code_id === cid);
                                        return (
                                            <li key={cid} className="text-sm">
                                                <span className="font-medium text-primary">{codeName(cid)}</span>
                                                {segs.length === 0 ? (
                                                    <span className="text-error-primary"> · no coded segment (the analysis stage will not validate)</span>
                                                ) : (
                                                    <ul className="pl-3 text-xs text-secondary">
                                                        {segs.map((x) => (
                                                            <li key={x.id}>
                                                                “{x.quote}” — {sourceTitle(x.contribution_id)}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>
        </div>
    );
}
