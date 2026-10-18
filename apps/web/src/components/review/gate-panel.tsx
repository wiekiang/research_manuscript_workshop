"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { ErrorAlert } from "@/components/research/error-alert";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { Project } from "@/lib/api/types";
import { humanize } from "@/lib/format";
import { STATE_LABEL } from "@/lib/states";

/**
 * Server-evaluated gates for one forward transition. Reasons are shown verbatim; the advance request is always
 * re-checked by the API.
 */
export function GatePanel({ project, fromState, toState, gateIds, onAdvanced }: { project: Project; fromState: string; toState: string; gateIds: string[]; onAdvanced: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const gates = (project.next_step?.gates ?? []).filter((g) => gateIds.includes(g.gate_id));
    const here = project.state === fromState;
    return (
        <div className="flex flex-col gap-3" data-testid={`gate-panel-${toState}`}>
            {!here ? (
                <p className="text-sm text-tertiary">
                    Evaluated in {STATE_LABEL[fromState as keyof typeof STATE_LABEL] ?? fromState}; the project is in {STATE_LABEL[project.state as keyof typeof STATE_LABEL] ?? project.state}.
                </p>
            ) : (
                <ul className="flex flex-col gap-2">
                    {gates.map((g) => (
                        <li key={g.gate_id} data-testid="gate" data-gate={g.gate_id} data-passed={g.passed} className="flex flex-col gap-1">
                            <p className="flex items-center gap-2 text-sm">
                                <StatusBadge status={g.passed ? "passed" : "blocked"} label={g.passed ? "Satisfied" : "Not satisfied"} />
                                <span className="font-mono text-secondary">{g.gate_id}</span>
                            </p>
                            {g.reasons.length > 0 && (
                                <ul className="list-disc pl-5 text-sm text-secondary">
                                    {g.reasons.map((r) => (
                                        <li key={r}>{r}</li>
                                    ))}
                                </ul>
                            )}
                        </li>
                    ))}
                </ul>
            )}
            <ErrorAlert error={error} />
            {here && project.my_role === "owner" && (
                <div>
                    <Button
                        size="sm"
                        isLoading={busy}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(`/v1/projects/${project.id}/advance`, { requested_state: toState, expected_version: project.version });
                                onAdvanced();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Move to {STATE_LABEL[toState as keyof typeof STATE_LABEL] ?? humanize(toState)}
                    </Button>
                </div>
            )}
        </div>
    );
}
