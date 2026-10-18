"use client";

import { useState } from "react";
import { PenTool02 } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { TextArea } from "@/components/base/textarea/textarea";
import { cx } from "@/utils/cx";
import { ErrorAlert } from "./error-alert";

export interface ApprovalSubmission {
    declaration_accepted: boolean;
    declaration_text: string;
    rationale?: string;
}

interface Props {
    gate: string;
    title: string;
    declaration: string;
    /** Reasons the gate cannot be signed yet; the signature control stays disabled while any exist. */
    blockingReasons?: string[];
    onSubmit: (body: ApprovalSubmission) => Promise<unknown>;
    submitLabel?: string;
    approvedManifestHash?: string | null;
    className?: string;
}

/**
 * Version-bound human signature. Shows the exact declaration served by the API, requires an explicit checkbox and is
 * disabled until every precondition is met. The approval itself is recorded and bound by the API, never here.
 */
export function ApprovalPanel({ gate, title, declaration, blockingReasons = [], onSubmit, submitLabel, approvedManifestHash, className }: Props) {
    const [accepted, setAccepted] = useState(false);
    const [rationale, setRationale] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const blocked = blockingReasons.length > 0;

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await onSubmit({ declaration_accepted: accepted, declaration_text: declaration, rationale: rationale || undefined });
            setAccepted(false);
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <section aria-labelledby={`approval-${gate}`} className={cx("flex flex-col gap-4 rounded-2xl border-2 border-utility-amber-300 bg-primary p-5", className)}>
            <header className="flex items-center gap-2">
                <PenTool02 className="size-5 text-fg-warning-primary" aria-hidden="true" />
                <h2 id={`approval-${gate}`} className="font-display text-lg font-semibold text-primary">
                    {title}
                </h2>
                <span className="ml-auto rounded-md bg-warning-primary px-2 py-0.5 text-xs font-semibold text-utility-amber-700">Human gate {gate}</span>
            </header>
            {blocked && (
                <div className="rounded-xl bg-secondary p-3" aria-live="polite">
                    <p className="text-sm font-medium text-secondary">You can sign once these are resolved:</p>
                    <ul className="mt-1 list-disc pl-5 text-sm text-tertiary">
                        {blockingReasons.map((r) => (
                            <li key={r}>{r}</li>
                        ))}
                    </ul>
                </div>
            )}
            <blockquote data-testid={`declaration-${gate}`} className="rounded-xl bg-secondary p-4 font-display text-md text-primary">
                {declaration}
            </blockquote>
            <Checkbox isSelected={accepted} onChange={setAccepted} isDisabled={blocked || busy} label="I have read this declaration and it is true for me" />
            <TextArea label="Rationale (optional)" value={rationale} onChange={setRationale} rows={2} placeholder="Context for your decision, recorded with the approval" isDisabled={blocked || busy} />
            <ErrorAlert error={error} />
            <div className="flex flex-wrap items-center gap-3">
                <Button color="primary" size="md" isDisabled={!accepted || blocked} isLoading={busy} onClick={submit}>
                    {submitLabel ?? `Sign ${gate}`}
                </Button>
                {approvedManifestHash && <span className="text-xs text-tertiary">Signed content manifest {approvedManifestHash.slice(0, 16)}</span>}
            </div>
        </section>
    );
}
