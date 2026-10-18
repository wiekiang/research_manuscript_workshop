"use client";

import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, PageHeader, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { Button } from "@/components/base/buttons/button";
import { useResource } from "@/hooks/use-resource";
import { humanize } from "@/lib/format";

interface ConferenceRow {
    edition_id: string;
    conference_id: string;
    name: string;
    acronym: string | null;
    year: number | null;
    status: string;
    official_cfp_url: string | null;
    venue_confidence: string;
    questionable_flag: boolean;
}

export default function ConferencesPage() {
    const { data, error, isLoading } = useResource<{ items: ConferenceRow[] }>("/v1/conferences");
    return (
        <div className="flex flex-col gap-10">
            <PageHeader title="Conferences" description="Editions imported into this workspace from official CFP sources. Import a CFP from a project's call-for-papers workspace." />
            <Section title="Imported editions">
                {isLoading && <Loading label="Loading conferences" />}
                <ErrorAlert error={error} />
                {data && data.items.length === 0 && <p className="text-sm text-tertiary">No conferences imported yet.</p>}
                <ul className="flex flex-col divide-y divide-secondary rounded-2xl bg-primary ring-1 ring-secondary">
                    {data?.items.map((c) => (
                        <li key={c.edition_id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                            <div className="min-w-0">
                                <p className="text-sm font-semibold text-primary">{c.name}</p>
                                {c.official_cfp_url && <p className="truncate text-xs text-tertiary">{c.official_cfp_url}</p>}
                            </div>
                            <div className="flex flex-wrap gap-2">
                                <StatusBadge status={c.status === "official" ? "confirmed" : "queued"} label={c.status === "official" ? "Official source confirmed" : "Exploratory"} />
                                <span className="text-xs text-tertiary">Venue confidence: {humanize(c.venue_confidence)}</span>
                                {c.questionable_flag && <StatusBadge status="blocked" label="Evidence-backed venue flag" />}
                            </div>
                        </li>
                    ))}
                </ul>
            </Section>
            <Section
                title="Automatic discovery"
                description="Discovery runs inside a project, against that project's research profile, and only fetches organizer sources a platform operator has verified in the official-source registry."
            >
                <div>
                    <Button href="/conferences/registry" color="secondary">
                        View the official-source registry
                    </Button>
                </div>
            </Section>
        </div>
    );
}
