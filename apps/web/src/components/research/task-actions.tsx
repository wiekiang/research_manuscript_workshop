"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { ErrorAlert } from "@/components/research/error-alert";
import { ApiError, api } from "@/lib/api/client";
import type { Task } from "@/lib/api/types";

export const CANCELLABLE = ["queued", "running", "waiting_human"];
export const RETRYABLE = ["failed_terminal", "cancelled"];

/**
 * Cancel a queued/running task or retry a failed/cancelled one from its recorded inputs (a new task; history is kept).
 * Billable kinds need an explicit cost confirmation, which the server asks for with `cost_confirmation_required`.
 */
export function TaskActions({ projectId, task, onChanged, canEdit = true }: { projectId: string; task: Task; onChanged?: () => void; canEdit?: boolean }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [needsCost, setNeedsCost] = useState(false);
    const [confirmCost, setConfirmCost] = useState(false);
    if (!canEdit || !projectId) return null;
    const canCancel = CANCELLABLE.includes(task.state);
    const canRetry = RETRYABLE.includes(task.state);
    if (!canCancel && !canRetry) return null;

    const run = async (action: "cancel" | "retry") => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/tasks/${task.id}/${action}`, action === "retry" ? { confirm_cost: confirmCost } : {});
            setNeedsCost(false);
            onChanged?.();
        } catch (err) {
            if (err instanceof ApiError && err.code === "cost_confirmation_required") setNeedsCost(true);
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-2" data-testid="task-actions">
            <div className="flex flex-wrap items-center gap-3">
                {canCancel && (
                    <Button size="sm" color="secondary" isLoading={busy} onClick={() => run("cancel")}>
                        Cancel task
                    </Button>
                )}
                {canRetry && (
                    <Button size="sm" color="secondary" isLoading={busy} isDisabled={needsCost && !confirmCost} onClick={() => run("retry")}>
                        Retry from recorded inputs
                    </Button>
                )}
                {canCancel && <span className="text-xs text-tertiary">Committed artifacts are kept and partial outputs stay labelled.</span>}
            </div>
            {needsCost && (
                <Checkbox
                    isSelected={confirmCost}
                    onChange={setConfirmCost}
                    label={`I accept that retrying can incur model or compute cost${task.estimated_cost_cents != null ? ` (estimate ${(task.estimated_cost_cents / 100).toFixed(2)})` : ""}`}
                />
            )}
            <ErrorAlert error={error} />
        </div>
    );
}
