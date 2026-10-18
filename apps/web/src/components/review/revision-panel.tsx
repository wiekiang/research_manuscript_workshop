"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { ReviewRound, Task } from "@/lib/api/types";
import { refusalHint } from "@/lib/review";

/** Automatic revision is limited to two cycles; its output is only a candidate the researcher applies or merges. */
export function RevisionPanel({ projectId, round, cycles, canEdit, onRequested }: { projectId: string; round: ReviewRound; cycles: { used: number; limit: number }; canEdit: boolean; onRequested: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [last, setLast] = useState<{ cycle: number; remaining: number; sections: string[] } | null>(null);
    const hint = refusalHint(error);
    return (
        <div className="flex flex-col gap-2" data-testid="revision-panel">
            <p className="text-sm text-secondary" data-testid="revision-cycles">
                Automatic revision cycles used: {cycles.used} of {cycles.limit}.
            </p>
            <p className="text-xs text-tertiary">
                A revision drafts new text for the sections that open blocker and major findings point at. It never changes the manuscript by itself: review the candidate and apply or merge it on the{" "}
                <a href={`/projects/${projectId}/manuscript`} className="text-brand-secondary underline-offset-2 hover:underline">
                    manuscript page
                </a>
                , then run the review again.
            </p>
            {canEdit && round.status === "complete" && (
                <div>
                    <Button
                        size="sm"
                        color="secondary"
                        isLoading={busy}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                const r = await api.post<{ task: Task; cycle: number; remaining: number; sections: string[] }>(`/v1/reviews/${round.id}/revise`, {});
                                setLast({ cycle: r.cycle, remaining: r.remaining, sections: r.sections });
                                onRequested();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Request automatic revision
                    </Button>
                </div>
            )}
            {last && (
                <p className="text-sm text-tertiary" role="status">
                    Revision cycle {last.cycle} requested for {last.sections.join(", ")}; {last.remaining} cycle(s) remain.
                </p>
            )}
            <ErrorAlert error={error} />
            {hint && <p className="text-sm text-tertiary">{hint}</p>}
        </div>
    );
}
