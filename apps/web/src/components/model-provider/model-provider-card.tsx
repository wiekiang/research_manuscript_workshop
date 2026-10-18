"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { RadioButton, RadioGroup } from "@/components/base/radio-buttons/radio-buttons";
import { ErrorAlert } from "@/components/research/error-alert";
import { StatusBadge } from "@/components/research/status-badge";
import type { ModelProviderKey, ModelProviderView } from "@/lib/api/types";
import { PROVIDER_EXPLANATIONS, needsDataFlow } from "@/lib/model-provider";

interface Props {
    view: ModelProviderView;
    onSelect: (provider: ModelProviderKey) => Promise<void>;
    /** Opens the data-flow attestation form preselected for this provider. */
    onAttest?: (provider: ModelProviderKey) => void;
}

/** The project owner chooses how this project reaches Claude; unavailable options stay visible with the reason. */
export function ModelProviderChoice({ view, onSelect, onAttest }: Props) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const attest = needsDataFlow(view);
    const attestLabel = view.options.find((o) => o.key === attest)?.label;

    return (
        <div className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <RadioGroup
                aria-label="AI provider for this project"
                value={view.selected ?? ""}
                isDisabled={!view.can_change || busy}
                onChange={async (value) => {
                    setBusy(true);
                    setError(undefined);
                    try {
                        await onSelect(value as ModelProviderKey);
                    } catch (err) {
                        setError(err);
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                {view.options.map((o) => (
                    <div key={o.key} className="flex flex-col gap-1" data-testid={`provider-option-${o.key}`}>
                        <RadioButton
                            value={o.key}
                            isDisabled={!o.available}
                            label={
                                <span className="inline-flex flex-wrap items-center gap-2">
                                    {o.label}
                                    {view.selected === o.key && <StatusBadge status="current" label="Selected" />}
                                </span>
                            }
                            hint={PROVIDER_EXPLANATIONS[o.key]}
                        />
                        {!o.available && o.reason && (
                            <p className="pl-6 text-sm text-warning-primary" data-testid={`provider-reason-${o.key}`}>
                                Not available: {o.reason}
                            </p>
                        )}
                    </div>
                ))}
            </RadioGroup>
            {!view.can_change && <p className="text-sm text-tertiary">Only the project owner can change the AI provider.</p>}
            <p className="text-sm text-tertiary">{view.note}</p>
            {attest && (
                <div role="status" className="flex flex-col gap-2 rounded-xl bg-warning-primary p-4 ring-1 ring-warning_subtle" data-testid="data-flow-cta">
                    <p className="text-sm text-primary">
                        AI calls on project data are refused until the project owner approves sending that data to <strong>{attestLabel}</strong>.
                    </p>
                    {onAttest && view.can_change && (
                        <div>
                            <Button size="sm" onClick={() => onAttest(attest)}>
                                Approve the data flow for this provider
                            </Button>
                        </div>
                    )}
                </div>
            )}
            <ErrorAlert error={error} />
        </div>
    );
}
