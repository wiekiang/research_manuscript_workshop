"use client";

import { useEffect, useId, useState } from "react";
import { XClose } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { ResearchProfileData } from "@/lib/api/types";

const EMPTY: ResearchProfileData = {
    topics: [],
    methods: [],
    geography: [],
    travel_budget: null,
    currency: "USD",
    desired_venues: [],
    lead_time_weeks: null,
    preferred_publishers: [],
    excluded_venues: [],
};

type ListKey = "topics" | "methods" | "geography" | "desired_venues" | "preferred_publishers" | "excluded_venues";

/** Free-text list entry: type a value and press Enter or "Add"; each value is removable by keyboard. */
export function TagListInput({ label, hint, values, onChange }: { label: string; hint?: string; values: string[]; onChange: (v: string[]) => void }) {
    const [draft, setDraft] = useState("");
    const id = useId();
    const add = () => {
        const v = draft.trim();
        if (v && !values.includes(v)) onChange([...values, v]);
        setDraft("");
    };
    return (
        <fieldset className="flex flex-col gap-2" aria-describedby={hint ? `${id}-hint` : undefined}>
            <legend className="text-sm font-medium text-secondary">{label}</legend>
            {hint && (
                <p id={`${id}-hint`} className="text-sm text-tertiary">
                    {hint}
                </p>
            )}
            {values.length > 0 && (
                <ul className="flex flex-wrap gap-2" aria-label={`${label} entries`}>
                    {values.map((v) => (
                        <li key={v} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-1 text-sm text-secondary ring-1 ring-secondary">
                            {v}
                            <button
                                type="button"
                                onClick={() => onChange(values.filter((x) => x !== v))}
                                className="rounded outline-focus-ring focus-visible:outline-2"
                                aria-label={`Remove ${v} from ${label}`}
                            >
                                <XClose className="size-3.5 text-fg-quaternary" aria-hidden="true" />
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            <div
                className="flex items-end gap-2"
                onKeyDown={(e) => {
                    if (e.key === "Enter") {
                        e.preventDefault();
                        add();
                    }
                }}
            >
                <Input aria-label={`Add to ${label}`} value={draft} onChange={setDraft} placeholder="Type and press Enter" className="flex-1" />
                <Button type="button" color="secondary" onClick={add} isDisabled={!draft.trim()}>
                    Add
                </Button>
            </div>
        </fieldset>
    );
}

/** Research profile editor. With `projectId` it edits the project-specific profile (layered over the default). */
export function ProfileEditor({ projectId, onSaved }: { projectId?: string; onSaved?: () => void }) {
    const path = projectId ? `/v1/research-profile?project_id=${projectId}` : "/v1/research-profile";
    const loaded = useResource<{ profile: ResearchProfileData }>(path);
    const [p, setP] = useState<ResearchProfileData>(EMPTY);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [saved, setSaved] = useState(false);

    useEffect(() => {
        if (loaded.data) setP({ ...EMPTY, ...loaded.data.profile });
    }, [loaded.data]);

    if (loaded.isLoading && !loaded.data) return <Loading label="Loading research profile" />;
    const setList = (k: ListKey) => (v: string[]) => {
        setSaved(false);
        setP({ ...p, [k]: v });
    };

    return (
        <form
            aria-label="Research profile"
            className="flex flex-col gap-5"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                try {
                    await api.put("/v1/research-profile", { ...p, project_id: projectId ?? null });
                    setSaved(true);
                    onSaved?.();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <ErrorAlert error={loaded.error} />
            <TagListInput label="Research topics" hint="Used for topic fit: the share of your terms that appear in each official CFP." values={p.topics} onChange={setList("topics")} />
            <TagListInput label="Methods" hint="e.g. benchmark, empirical, qualitative, theoretical" values={p.methods} onChange={setList("methods")} />
            <TagListInput label="Preferred geography" values={p.geography} onChange={setList("geography")} />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Input
                    label="Travel budget"
                    type="number"
                    value={p.travel_budget === null ? "" : String(p.travel_budget)}
                    onChange={(v) => {
                        setSaved(false);
                        setP({ ...p, travel_budget: v === "" ? null : Number(v) });
                    }}
                />
                <Input label="Currency" value={p.currency} onChange={(v) => setP({ ...p, currency: v.toUpperCase().slice(0, 3) })} />
                <Input
                    label="Lead time (weeks)"
                    hint="Time you need before a full-paper deadline"
                    type="number"
                    value={p.lead_time_weeks === null ? "" : String(p.lead_time_weeks)}
                    onChange={(v) => {
                        setSaved(false);
                        setP({ ...p, lead_time_weeks: v === "" ? null : Math.max(0, Math.round(Number(v))) });
                    }}
                />
            </div>
            <TagListInput label="Desired venues" values={p.desired_venues} onChange={setList("desired_venues")} />
            <TagListInput label="Preferred publishers" values={p.preferred_publishers} onChange={setList("preferred_publishers")} />
            <TagListInput label="Excluded venues" hint="Matched against a venue's name or acronym; excluded venues are listed separately, never hidden." values={p.excluded_venues} onChange={setList("excluded_venues")} />
            <ErrorAlert error={error} />
            {saved && (
                <p role="status" className="text-sm text-success-primary">
                    Profile saved.
                </p>
            )}
            <div>
                <Button type="submit" isLoading={busy}>
                    Save profile
                </Button>
            </div>
        </form>
    );
}
