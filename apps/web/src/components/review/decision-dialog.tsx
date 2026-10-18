"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import { refusalHint } from "@/lib/review";

const DECISIONS = [
    { value: "resolved", label: "Resolved (I checked it and it is satisfied)" },
    { value: "accepted_risk", label: "Accept the risk" },
    { value: "not_applicable", label: "Not applicable to this submission" },
];

/**
 * Signed human decision on a manual check or warning. The exact declaration text comes from the API; the decision is
 * recorded with the signer's name and cannot be changed.
 */
export function DecisionDialog({ isOpen, onOpenChange, path, checkId, detail, declaration, onDone }: {
    isOpen: boolean;
    onOpenChange: (o: boolean) => void;
    path: string;
    checkId: string;
    detail: string;
    declaration: string;
    onDone: () => void;
}) {
    const [decision, setDecision] = useState("resolved");
    const [rationale, setRationale] = useState("");
    const [accepted, setAccepted] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const hint = refusalHint(error);
    return (
        <DialogShell
            isOpen={isOpen}
            onOpenChange={onOpenChange}
            title={`Signed decision: ${checkId}`}
            description={detail}
            footer={
                <>
                    <Button color="secondary" size="sm" onClick={() => onOpenChange(false)}>
                        Close
                    </Button>
                    <Button
                        size="sm"
                        isLoading={busy}
                        isDisabled={!accepted || rationale.trim().length < 20}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(path, { decision, rationale, declaration_accepted: accepted, declaration_text: declaration });
                                onDone();
                                onOpenChange(false);
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Sign decision
                    </Button>
                </>
            }
        >
            <NativeSelect label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)} options={DECISIONS} />
            <TextArea label="Rationale (your own words, at least 20 characters)" value={rationale} onChange={setRationale} rows={3} />
            <blockquote data-testid="decision-declaration" className="rounded-xl bg-secondary p-4 text-sm text-primary">
                {declaration}
            </blockquote>
            <Checkbox isSelected={accepted} onChange={setAccepted} label="I have read this declaration and it is true for me" />
            <ErrorAlert error={error} />
            {hint && <p className="text-sm text-tertiary">{hint}</p>}
        </DialogShell>
    );
}
