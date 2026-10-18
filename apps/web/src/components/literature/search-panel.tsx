"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import type { Resource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { LiteratureSetup, SearchRunEntry } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { PROVIDER_STATUS } from "@/lib/literature";

export function LiteratureSetupPanel({ setup }: { setup: Resource<LiteratureSetup> }) {
    if (setup.isLoading && !setup.data) return <Loading label="Loading literature sources" />;
    if (setup.error) return <ErrorAlert error={setup.error} />;
    const s = setup.data;
    if (!s) return null;
    return (
        <section aria-labelledby="lit-setup-title" className="flex flex-col gap-3 rounded-2xl bg-secondary_subtle p-5 ring-1 ring-secondary">
            <h2 id="lit-setup-title" className="font-display text-lg font-semibold text-primary">
                Literature search
            </h2>
            <p data-testid="literature-setup-message" className="max-w-prose text-sm text-secondary">
                {s.message}
            </p>
            <div className="flex flex-col gap-1">
                <h3 className="text-sm font-semibold text-secondary">Sources enabled for this workspace</h3>
                <ul className="flex flex-col gap-1 text-sm text-tertiary">
                    {s.enabled_sources.map((src) => (
                        <li key={src.key}>
                            <span className="font-medium text-primary">{src.name}</span>
                            {src.attribution && <> — {src.attribution}</>}
                        </li>
                    ))}
                </ul>
            </div>
            {s.optional_connections.length > 0 && (
                <p className="text-sm text-tertiary">
                    Optional connected accounts available: {s.optional_connections.map((c) => c.name).join(", ")}. Manage them in settings.
                </p>
            )}
        </section>
    );
}

/** Sources a search may use: the API only returns enabled, non-blocked sources that support search. */
function searchableSources(setup: LiteratureSetup | undefined): { key: string; name: string }[] {
    // DataCite is an identity registry, not a search source.
    return (setup?.enabled_sources ?? []).filter((s) => s.key !== "datacite");
}

export function SearchForm({ projectId, setup, onQueued }: { projectId: string; setup: LiteratureSetup | undefined; onQueued: () => void }) {
    const sources = searchableSources(setup);
    const [query, setQuery] = useState("");
    const [providers, setProviders] = useState<string[]>([]);
    const [yearFrom, setYearFrom] = useState("");
    const [yearTo, setYearTo] = useState("");
    const [max, setMax] = useState("25");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [refused, setRefused] = useState<{ provider: string; reason: string }[]>([]);
    const [queued, setQueued] = useState(false);

    useEffect(() => {
        if (providers.length === 0 && sources.length) setProviders(sources.map((s) => s.key));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sources.length]);

    return (
        <form
            className="flex flex-col gap-3 rounded-2xl bg-primary p-5 ring-1 ring-secondary"
            aria-label="New literature search"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                setQueued(false);
                try {
                    const res = await api.post<{ refused: { provider: string; reason: string }[] }>(`/v1/projects/${projectId}/searches`, {
                        query,
                        providers,
                        year_from: yearFrom ? Number(yearFrom) : null,
                        year_to: yearTo ? Number(yearTo) : null,
                        max_results: Number(max) || 25,
                    });
                    setRefused(res.refused ?? []);
                    setQueued(true);
                    onQueued();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <Input label="Search query" isRequired value={query} onChange={setQuery} hint="The exact query string is recorded with the search date and results." />
            <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium text-secondary">Sources</legend>
                <div className="flex flex-wrap gap-4">
                    {sources.map((s) => (
                        <Checkbox
                            key={s.key}
                            label={s.name}
                            isSelected={providers.includes(s.key)}
                            onChange={(on) => setProviders((p) => (on ? [...p, s.key] : p.filter((x) => x !== s.key)))}
                        />
                    ))}
                </div>
            </fieldset>
            <div className="grid gap-3 sm:grid-cols-3">
                <Input label="From year" inputMode="numeric" value={yearFrom} onChange={setYearFrom} />
                <Input label="To year" inputMode="numeric" value={yearTo} onChange={setYearTo} />
                <Input label="Maximum results per source" inputMode="numeric" value={max} onChange={setMax} />
            </div>
            <ErrorAlert error={error} />
            {queued && <p className="text-sm text-success-primary">Search queued. Results appear in the papers list when the task finishes.</p>}
            {refused.length > 0 && (
                <ul className="text-sm text-warning-primary">
                    {refused.map((r) => (
                        <li key={r.provider}>
                            {r.provider} was not used: {r.reason}
                        </li>
                    ))}
                </ul>
            )}
            <div>
                <Button type="submit" isLoading={busy} isDisabled={query.trim().length < 3 || providers.length === 0}>
                    Search
                </Button>
            </div>
        </form>
    );
}

export function SearchHistory({ runs }: { runs: SearchRunEntry[] }) {
    return (
        <Section id="search-history" title="Search history" description="Every search keeps its exact query, filters, date and the outcome per source. Coverage counts are derived from these records.">
            {runs.length === 0 && <p className="text-sm text-tertiary">No searches yet.</p>}
            <ul className="flex flex-col gap-3">
                {runs.map((r) => (
                    <li key={r.id} data-testid="search-run" className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium text-primary">“{r.query}”</span>
                            <StatusBadge status={r.status === "succeeded" ? "succeeded" : r.status === "partial" ? "partial" : r.status} />
                            <span className="text-xs text-tertiary">
                                {r.executed_at ? `executed ${formatDateTime(r.executed_at)}` : `requested ${formatDateTime(r.created_at)}`} · {r.retrieved_count} records
                                {r.filters?.year_from || r.filters?.year_to ? ` · years ${r.filters.year_from ?? "…"}–${r.filters.year_to ?? "…"}` : ""}
                            </span>
                        </div>
                        <ul className="flex flex-wrap gap-2">
                            {Object.entries(r.provider_status ?? {}).map(([name, st]) => {
                                const spec = PROVIDER_STATUS[st.status] ?? { label: st.status, status: "not_performed" };
                                return (
                                    <li key={name} className="flex flex-col gap-0.5 rounded-lg bg-secondary px-2 py-1 text-xs">
                                        <span className="flex items-center gap-1">
                                            <span className="font-medium text-secondary">{name}</span>
                                            <StatusBadge status={spec.status} label={spec.label} />
                                        </span>
                                        {typeof st.retrieved === "number" && st.status !== "refused" && (
                                            <span className="text-tertiary">
                                                {st.retrieved} retrieved{st.total_reported != null ? ` of ${st.total_reported} reported` : ""}
                                            </span>
                                        )}
                                        {(st.error || st.reason) && <span className="text-error-primary">{st.error ?? st.reason}</span>}
                                    </li>
                                );
                            })}
                        </ul>
                    </li>
                ))}
            </ul>
        </Section>
    );
}
