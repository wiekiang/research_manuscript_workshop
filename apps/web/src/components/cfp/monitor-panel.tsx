"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { ApiError, api } from "@/lib/api/client";
import type { MonitorCheck } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const NEXT_ACTION: Record<string, string> = {
    no_target: "Select an official target edition and track first.",
    no_fetched_source: "This CFP was supplied as a document. Re-import it from its official URL to enable change monitoring.",
};

/** CFP change monitoring: conditional refetch of the target's official page and the history of checks. */
export function MonitorPanel({ projectId, isOwner, onQueued }: { projectId: string; isOwner: boolean; onQueued: () => void }) {
    const history = useResource<{ items: MonitorCheck[] }>(`/v1/projects/${projectId}/cfp/monitor`, 5000);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [queued, setQueued] = useState(false);
    const code = error instanceof ApiError ? error.code : null;

    return (
        <Section
            title="Official CFP monitoring"
            description="The platform re-checks the target's official page daily using conditional requests. A change re-runs extraction and reopens only the confirmations that depended on the changed rules; deadline-only changes refresh the schedule without reopening your rule confirmation."
            actions={
                isOwner ? (
                    <Button
                        color="secondary"
                        isLoading={busy}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            setQueued(false);
                            try {
                                await api.post(`/v1/projects/${projectId}/cfp/check-now`);
                                setQueued(true);
                                onQueued();
                                void history.reload();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Check official CFP now
                    </Button>
                ) : undefined
            }
        >
            {code && NEXT_ACTION[code] ? (
                <p role="alert" className="rounded-xl bg-secondary_subtle p-3 text-sm text-secondary ring-1 ring-secondary">
                    {NEXT_ACTION[code]}
                </p>
            ) : (
                <ErrorAlert error={error} />
            )}
            {queued && <p className="text-sm text-success-primary">Check queued. Results appear in the history below.</p>}
            <ErrorAlert error={history.error} />
            {history.data && history.data.items.length === 0 && <p className="text-sm text-tertiary">No checks yet.</p>}
            {history.data && history.data.items.length > 0 && (
                <ul className="flex flex-col divide-y divide-secondary rounded-xl bg-primary ring-1 ring-secondary" data-testid="monitor-history">
                    {history.data.items.slice(0, 10).map((c) => (
                        <li key={c.id} className="flex flex-col gap-1 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <StatusBadge status={c.outcome} />
                                <span className="text-xs text-tertiary">{formatDateTime(c.at)}</span>
                            </div>
                            <p className="text-xs break-all text-tertiary">{c.url}</p>
                            {c.detail && <p className="text-xs text-secondary">{c.detail}</p>}
                        </li>
                    ))}
                </ul>
            )}
        </Section>
    );
}
