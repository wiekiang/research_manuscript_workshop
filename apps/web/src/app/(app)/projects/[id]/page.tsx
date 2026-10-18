"use client";

import { useState } from "react";
import { PauseCircle, PlayCircle, SlashCircle01 } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { TextArea } from "@/components/base/textarea/textarea";
import { useProject } from "@/components/project/project-context";
import { BudgetBar, CostLimitNotice } from "@/components/research/cost-limit-notice";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { NextActionPanel } from "@/components/research/next-action-panel";
import { Section } from "@/components/research/page-header";
import { StageTimeline } from "@/components/research/stage-timeline";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";

const GATES = ["CFP", "H1", "H2", "H3", "H4"] as const;
const GATE_NAMES: Record<string, string> = {
    CFP: "Track and CFP rules",
    H1: "Research direction and contribution",
    H2: "Methodology and protocol",
    H3: "Outcomes and interpretation",
    H4: "Final manuscript and submission",
};

type ControlAction = "pause" | "resume" | "cancel";

export default function ProjectOverview() {
    const { project, reload } = useProject();
    const [action, setAction] = useState<ControlAction | null>(null);
    const [reason, setReason] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    if (!project) return null;
    const isOwner = project.my_role === "owner";
    const overlay = ["PAUSED", "BLOCKED"].includes(project.state);
    const cancelled = project.state === "CANCELLED";

    const control = async () => {
        if (!action) return;
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${project.id}/${action}`, { expected_version: project.version, reason: reason || null });
            setAction(null);
            setReason("");
            await reload();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="flex flex-col gap-8">
                <NextActionPanel projectId={project.id} state={project.state} nextStep={project.next_step} />
                <CostLimitNotice budget={project.budget} />
                <Section title="Human approvals" description="Each approval binds the exact content you signed. A change to that content invalidates only the approvals that depended on it.">
                    <ul className="flex flex-col divide-y divide-secondary rounded-2xl bg-primary ring-1 ring-secondary">
                        {GATES.map((g) => {
                            const a = project.approvals?.find((x) => x.gate === g);
                            return (
                                <li key={g} className="flex flex-col gap-1 p-4 sm:flex-row sm:items-center sm:justify-between">
                                    <div>
                                        <p className="text-sm font-semibold text-primary">
                                            {g}: {GATE_NAMES[g]}
                                        </p>
                                        {a?.invalidation_reason && <p className="text-sm text-tertiary">Invalidated because {a.invalidation_reason}</p>}
                                        {a && a.status === "valid" && <p className="text-xs text-tertiary">Signed {formatDateTime(a.decided_at)}</p>}
                                    </div>
                                    {a ? <StatusBadge status={a.status} /> : <StatusBadge status="queued" label="Not signed yet" />}
                                </li>
                            );
                        })}
                    </ul>
                </Section>
                {Array.isArray(project.waiting_human_tasks) && project.waiting_human_tasks.length > 0 && (
                    <Section title="Tasks waiting for you">
                        <ul className="flex flex-col gap-2">
                            {project.waiting_human_tasks.map((t) => (
                                <li key={t.id} className="rounded-xl bg-warning-primary p-3 text-sm text-utility-amber-700">
                                    {t.kind}: {t.reason ?? "a decision is needed"}
                                </li>
                            ))}
                        </ul>
                    </Section>
                )}
            </div>
            <aside className="flex flex-col gap-6" aria-label="Project status">
                <div className="rounded-2xl bg-primary p-5 ring-1 ring-secondary">
                    <StageTimeline state={project.state} resumeState={project.resume_state} overlayReason={project.overlay_reason} />
                </div>
                {project.budget && (
                    <div className="flex flex-col gap-3 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
                        <h2 className="text-sm font-semibold text-primary">Budget</h2>
                        <BudgetBar budget={project.budget} />
                        <Button color="link-color" size="sm" href={`/projects/${project.id}/costs`}>
                            View costs
                        </Button>
                    </div>
                )}
                {isOwner && !cancelled && (
                    <div className="flex flex-col gap-2 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
                        <h2 className="text-sm font-semibold text-primary">Workflow control</h2>
                        {overlay ? (
                            <Button color="secondary" iconLeading={PlayCircle} onClick={() => setAction("resume")}>
                                Resume project
                            </Button>
                        ) : (
                            <Button color="secondary" iconLeading={PauseCircle} onClick={() => setAction("pause")}>
                                Pause project
                            </Button>
                        )}
                        <Button color="secondary-destructive" iconLeading={SlashCircle01} onClick={() => setAction("cancel")}>
                            Cancel project
                        </Button>
                    </div>
                )}
            </aside>
            <DialogShell
                isOpen={action !== null}
                onOpenChange={(o) => !o && setAction(null)}
                title={action === "cancel" ? "Cancel this project?" : action === "pause" ? "Pause this project?" : "Resume this project?"}
                description={
                    action === "cancel"
                        ? "Queued work stops and running tasks are signalled to stop. Artifacts and the audit history are kept. A cancelled project cannot be resumed."
                        : action === "pause"
                          ? "No new billable work starts while paused. Running tasks wait at their next checkpoint."
                          : "Work continues from the saved stage."
                }
                footer={
                    <>
                        <Button color="secondary" onClick={() => setAction(null)}>
                            Keep as is
                        </Button>
                        <Button color={action === "cancel" ? "primary-destructive" : "primary"} isLoading={busy} onClick={control}>
                            {action === "cancel" ? "Cancel project" : action === "pause" ? "Pause project" : "Resume project"}
                        </Button>
                    </>
                }
            >
                {action !== "resume" && <TextArea label="Reason (recorded in the audit history)" value={reason} onChange={setReason} rows={2} />}
                <ErrorAlert error={error} />
            </DialogShell>
        </div>
    );
}
