"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import { CATEGORY_LABEL, CLAIM_CATEGORIES, CLAIM_KINDS } from "@/lib/literature";

const KIND_LABEL: Record<string, string> = {
    literature: "Literature claim",
    observed_result: "Observed result",
    interpretation: "Interpretation",
    hypothesis: "Hypothesis",
    limitation: "Limitation",
};

export function CreateClaimDialog({ projectId, onClose, onDone }: { projectId: string; onClose: () => void; onDone: () => void }) {
    const [proposition, setProposition] = useState("");
    const [kind, setKind] = useState("literature");
    const [category, setCategory] = useState("descriptive");
    const [fields, setFields] = useState({ subject: "", population_or_dataset: "", measure: "", comparison: "", time: "", scope: "" });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const set = (k: keyof typeof fields) => (v: string) => setFields((f) => ({ ...f, [k]: v }));
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Register a claim"
            size="lg"
            description="One distinct proposition per claim. Numerical, causal, comparative, novelty, policy and central-conclusion claims are critical and need human-inspectable support."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        isLoading={busy}
                        isDisabled={proposition.trim().length < 5}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                const body: Record<string, string | null> = { proposition, kind, category };
                                for (const [k, v] of Object.entries(fields)) body[k] = v.trim() || null;
                                await api.post(`/v1/projects/${projectId}/claims`, body);
                                onDone();
                                onClose();
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Register claim
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <TextArea label="Proposition" isRequired value={proposition} onChange={setProposition} rows={3} />
                <div className="grid gap-3 sm:grid-cols-2">
                    <NativeSelect label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} options={CLAIM_KINDS.map((k) => ({ label: KIND_LABEL[k], value: k }))} />
                    <NativeSelect label="Category" value={category} onChange={(e) => setCategory(e.target.value)} options={CLAIM_CATEGORIES.map((c) => ({ label: CATEGORY_LABEL[c], value: c }))} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                    <Input label="Subject" value={fields.subject} onChange={set("subject")} />
                    <Input label="Population or dataset" value={fields.population_or_dataset} onChange={set("population_or_dataset")} />
                    <Input label="Measure" value={fields.measure} onChange={set("measure")} />
                    <Input label="Comparison" value={fields.comparison} onChange={set("comparison")} />
                    <Input label="Time" value={fields.time} onChange={set("time")} />
                    <Input label="Scope" value={fields.scope} onChange={set("scope")} />
                </div>
                <ErrorAlert error={error} />
            </div>
        </DialogShell>
    );
}
