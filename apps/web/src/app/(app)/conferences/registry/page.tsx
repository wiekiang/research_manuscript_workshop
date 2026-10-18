"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { TagListInput } from "@/components/discovery/profile-editor";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, PageHeader, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { ApiError, api } from "@/lib/api/client";
import type { RegistryEntry } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

function OperatorForm({ onSaved }: { onSaved: () => void }) {
    const [f, setF] = useState({ series_key: "", name: "", acronym: "", organizer: "", publisher: "", homepage_url: "", notes: "", verification_status: "unverified_seed" });
    const [cfpUrls, setCfpUrls] = useState<string[]>([]);
    const [keywords, setKeywords] = useState<string[]>([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [denied, setDenied] = useState(false);
    const [saved, setSaved] = useState(false);
    const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
    if (denied) {
        return (
            <p role="status" className="rounded-xl bg-secondary_subtle p-4 text-sm text-secondary ring-1 ring-secondary">
                The registry is read-only for your account. Only platform operators (with multi-factor authentication) can add or verify official sources.
            </p>
        );
    }
    return (
        <form
            aria-label="Add or update a registry source"
            className="flex flex-col gap-3"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                setSaved(false);
                try {
                    await api.put("/v1/registry", {
                        ...f,
                        acronym: f.acronym || null,
                        organizer: f.organizer || null,
                        publisher: f.publisher || null,
                        notes: f.notes || null,
                        cfp_urls: cfpUrls,
                        keywords,
                        questionable_evidence: [],
                    });
                    setSaved(true);
                    onSaved();
                } catch (err) {
                    if (err instanceof ApiError && err.status === 403) setDenied(true);
                    else setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Input label="Series key" isRequired value={f.series_key} onChange={set("series_key")} hint="Stable identifier, e.g. icrds" />
                <Input label="Name" isRequired value={f.name} onChange={set("name")} />
                <Input label="Acronym" value={f.acronym} onChange={set("acronym")} />
                <Input label="Organizer" value={f.organizer} onChange={set("organizer")} />
                <Input label="Publisher" value={f.publisher} onChange={set("publisher")} />
                <Input label="Official homepage URL" type="url" isRequired value={f.homepage_url} onChange={set("homepage_url")} />
            </div>
            <TagListInput label="Official CFP URLs" values={cfpUrls} onChange={setCfpUrls} />
            <TagListInput label="Keywords" values={keywords} onChange={setKeywords} />
            <NativeSelect
                label="Verification status"
                value={f.verification_status}
                onChange={(e) => set("verification_status")(e.target.value)}
                options={[
                    { label: "Unverified seed (not used by discovery)", value: "unverified_seed" },
                    { label: "Verified official source", value: "verified" },
                    { label: "Retired", value: "retired" },
                ]}
            />
            <TextArea label="Notes" value={f.notes} onChange={set("notes")} rows={2} />
            <ErrorAlert error={error} />
            {saved && <p className="text-sm text-success-primary">Saved.</p>}
            <div>
                <Button type="submit" isLoading={busy} isDisabled={!f.series_key || !f.name || !f.homepage_url}>
                    Save source
                </Button>
            </div>
        </form>
    );
}

export default function RegistryPage() {
    const reg = useResource<{ items: RegistryEntry[] }>("/v1/registry");
    return (
        <div className="flex flex-col gap-10">
            <PageHeader
                title="Official-source registry"
                description="Organizer websites that automatic discovery may fetch. Only verified entries are used. A concern about a venue is shown only with its cited source, never as an automated accusation."
            />
            <Section title="Sources">
                {reg.isLoading && <Loading label="Loading registry" />}
                <ErrorAlert error={reg.error} />
                {reg.data && reg.data.items.length === 0 && <p className="text-sm text-tertiary">The registry is empty. Discovery is unavailable until a platform operator verifies official sources; manual CFP import still works.</p>}
                <ul className="flex flex-col gap-3">
                    {reg.data?.items.map((r) => (
                        <li key={r.id} data-testid="registry-entry" className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="text-sm font-semibold text-primary">
                                    {r.name}
                                    {r.acronym && <span className="text-tertiary"> · {r.acronym}</span>}
                                </span>
                                <StatusBadge status={r.verification_status} />
                                {r.publisher && <span className="text-xs text-tertiary">{r.publisher}</span>}
                            </div>
                            <p className="text-xs break-all text-tertiary">Homepage: {r.homepage_url}</p>
                            {r.cfp_urls.length > 0 && <p className="text-xs break-all text-tertiary">CFP: {r.cfp_urls.join(", ")}</p>}
                            {r.verified_by && (
                                <p className="text-xs text-tertiary">
                                    Verified by {r.verified_by} {r.verified_at ? `on ${formatDateTime(r.verified_at)}` : ""}
                                </p>
                            )}
                            {r.questionable_evidence.length > 0 && (
                                <ul className="list-disc pl-5 text-xs text-utility-amber-700">
                                    {r.questionable_evidence.map((e, i) => (
                                        <li key={i}>
                                            {e.note}{" "}
                                            {e.source_url && (
                                                <a href={e.source_url} target="_blank" rel="noopener noreferrer" className="underline">
                                                    source
                                                </a>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </li>
                    ))}
                </ul>
            </Section>
            <Section title="Curate a source" description="Platform operators only. Every URL is checked against the egress policy before it is saved.">
                <OperatorForm onSaved={() => void reg.reload()} />
            </Section>
        </div>
    );
}
