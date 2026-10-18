"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { ManuscriptVersion } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { VERSION_ORIGIN_LABEL } from "@/lib/manuscript";
import { SpanView } from "./span-view";

/** Every committed manuscript version (immutable artifacts), newest first. */
export function VersionsPanel({ projectId, manuscriptId, tick }: { projectId: string; manuscriptId: string; tick: number }) {
    const list = useResource<{ items: ManuscriptVersion[] }>(`/v1/manuscripts/${manuscriptId}/versions`);
    const [open, setOpen] = useState<number | null>(null);
    const [detail, setDetail] = useState<ManuscriptVersion>();
    const [error, setError] = useState<unknown>();

    useEffect(() => {
        void list.reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [tick]);
    useEffect(() => {
        setDetail(undefined);
        setError(undefined);
        if (open == null) return;
        api.get<ManuscriptVersion>(`/v1/manuscripts/${manuscriptId}/versions/${open}`).then(setDetail, setError);
    }, [open, manuscriptId]);

    return (
        <Section title="Version history" description="Each version is an immutable artifact; reviews and approvals bind to a specific version.">
            <ErrorAlert error={list.error} />
            <ul className="flex flex-col gap-1">
                {(list.data?.items ?? []).map((v) => (
                    <li key={v.id} data-testid="version-row" data-origin={v.origin} className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="font-medium text-primary">v{v.version}</span>
                        <span className="text-secondary">{VERSION_ORIGIN_LABEL[v.origin] ?? v.origin}</span>
                        <span className="text-xs text-tertiary">
                            {formatDateTime(v.created_at)} · {v.checks.blockers ?? 0} blocker(s) · {v.checks.unresolved_claims ?? 0} unresolved claim(s)
                        </span>
                        {v.change_summary && <span className="text-xs text-tertiary">— {v.change_summary}</span>}
                        <Button size="sm" color="link-color" onClick={() => setOpen(v.version)}>
                            View
                        </Button>
                    </li>
                ))}
            </ul>
            <DialogShell isOpen={open != null} onOpenChange={(o) => !o && setOpen(null)} size="lg" title={`Manuscript version ${open ?? ""}`} description={detail ? `hash ${detail.content_hash.slice(0, 16)}` : undefined}>
                <div className="flex max-h-[65vh] flex-col gap-4 overflow-y-auto pr-1">
                    <ErrorAlert error={error} />
                    {!detail && !error && <Loading label="Loading version" />}
                    {detail?.content?.sections.map((s) => (
                        <div key={s.key} className="flex flex-col gap-2">
                            <h3 className="text-md font-semibold text-primary">{s.heading}</h3>
                            {s.paragraphs.length === 0 && <p className="text-sm text-tertiary">Empty.</p>}
                            {s.paragraphs.map((p, i) => (
                                <div key={i} className="flex flex-col gap-1.5">
                                    {p.spans.map((sp) => (
                                        <SpanView key={sp.span_id} span={sp} record={detail.spans.find((r) => r.span_id === sp.span_id)} projectId={projectId} />
                                    ))}
                                </div>
                            ))}
                        </div>
                    ))}
                </div>
            </DialogShell>
        </Section>
    );
}
