"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { AnthropicConnection, ModelConnections } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

interface ViewProps {
    connection: AnthropicConnection;
    onConnect: (apiKey: string, consentText: string) => Promise<void>;
    onDisconnect: () => Promise<void>;
}

/** Presentational card: the key lives only in the input while typing and is cleared on submit, success or failure. */
export function AnthropicConnectionView({ connection, onConnect, onDisconnect }: ViewProps) {
    const [apiKey, setApiKey] = useState("");
    const [accepted, setAccepted] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [confirmOpen, setConfirmOpen] = useState(false);

    const submit = async () => {
        const key = apiKey;
        setApiKey(""); // never keep the key in component state after submitting
        setBusy(true);
        setError(undefined);
        try {
            await onConnect(key, connection.consent_text);
            setAccepted(false);
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-primary">Anthropic API key</span>
                {connection.connected ? (
                    <StatusBadge status="current" label={`Connected (key ${connection.key_hint ?? "hidden"})`} />
                ) : (
                    <StatusBadge status="queued" label="Not connected" />
                )}
            </div>
            {connection.connected ? (
                <>
                    <p className="text-sm text-tertiary">
                        Connected {connection.connected_at ? formatDateTime(connection.connected_at) : ""}. Only the last characters of the key are ever shown. Projects you own can
                        choose &quot;My Anthropic API key&quot; as their AI provider.
                    </p>
                    <div>
                        <Button color="secondary-destructive" onClick={() => setConfirmOpen(true)}>
                            Disconnect key
                        </Button>
                    </div>
                </>
            ) : (
                <form
                    className="flex flex-col gap-3"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void submit();
                    }}
                >
                    <Input label="API key" type="password" autoComplete="off" value={apiKey} onChange={setApiKey} placeholder="sk-ant-…" />
                    <blockquote className="rounded-xl bg-secondary p-4 text-sm text-primary" data-testid="model-consent-text">
                        {connection.consent_text}
                    </blockquote>
                    <Checkbox isSelected={accepted} onChange={setAccepted} label="I accept this statement" />
                    <div>
                        <Button type="submit" isLoading={busy} isDisabled={!apiKey || !accepted}>
                            Connect key
                        </Button>
                    </div>
                </form>
            )}
            <ErrorAlert error={error} />
            <DialogShell
                isOpen={confirmOpen}
                onOpenChange={setConfirmOpen}
                title="Disconnect your Anthropic API key?"
                description="The stored key is destroyed. Projects that use “My Anthropic API key” stop making AI calls until you connect a key again or choose another provider."
                footer={
                    <>
                        <Button color="secondary" onClick={() => setConfirmOpen(false)}>
                            Cancel
                        </Button>
                        <Button
                            color="primary-destructive"
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    await onDisconnect();
                                    setConfirmOpen(false);
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Disconnect
                        </Button>
                    </>
                }
            >
                <ErrorAlert error={error} />
            </DialogShell>
        </div>
    );
}

/** Account settings: researcher-owned AI provider connections. */
export function ModelConnectionsCard() {
    const conns = useResource<ModelConnections>("/v1/me/model-connections");
    if (conns.isLoading && !conns.data) return <Loading label="Loading AI provider connections" />;
    if (!conns.data) return <ErrorAlert error={conns.error} />;
    return (
        <AnthropicConnectionView
            connection={conns.data.anthropic}
            onConnect={async (apiKey, consentText) => {
                await api.put("/v1/me/model-connections/anthropic", { api_key: apiKey, consent_accepted: true, consent_text: consentText });
                await conns.reload();
            }}
            onDisconnect={async () => {
                await api.del("/v1/me/model-connections/anthropic");
                await conns.reload();
            }}
        />
    );
}
