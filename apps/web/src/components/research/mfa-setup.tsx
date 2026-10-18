"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { api } from "@/lib/api/client";
import { ErrorAlert } from "./error-alert";

/** TOTP enrolment: the secret is shown once; the QR code is rendered locally from the otpauth URI. */
export function MfaSetup({ enabled, onEnabled }: { enabled: boolean; onEnabled?: () => void }) {
    const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
    const [code, setCode] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [done, setDone] = useState(enabled);
    const qrRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!setup || !qrRef.current) return;
        let cancelled = false;
        void import("qr-code-styling").then(({ default: QRCodeStyling }) => {
            if (cancelled || !qrRef.current) return;
            qrRef.current.innerHTML = "";
            new QRCodeStyling({ width: 180, height: 180, data: setup.otpauth_uri, type: "svg" }).append(qrRef.current);
        });
        return () => {
            cancelled = true;
        };
    }, [setup]);

    if (done) return <p className="text-sm text-success-primary">Multi-factor authentication is on for this account.</p>;

    return (
        <div className="flex flex-col gap-4">
            {!setup ? (
                <div>
                    <Button
                        color="secondary"
                        isLoading={busy}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                setSetup(await api.post("/v1/auth/mfa/setup"));
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Set up an authenticator app
                    </Button>
                </div>
            ) : (
                <div className="flex flex-col gap-3">
                    <p className="text-sm text-secondary">Scan the code with your authenticator app, or enter the key manually. It is shown only once.</p>
                    <div ref={qrRef} aria-label="QR code for the authenticator app" role="img" className="w-fit rounded-lg bg-white p-2" />
                    <p className="font-mono text-sm break-all text-primary">{setup.secret}</p>
                    <Input label="Code from the app" inputMode="numeric" value={code} onChange={setCode} />
                    <div>
                        <Button
                            isLoading={busy}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    await api.post("/v1/auth/mfa/enable", { code });
                                    setDone(true);
                                    onEnabled?.();
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Turn on multi-factor authentication
                        </Button>
                    </div>
                    <p className="text-xs text-tertiary">After turning it on, sign in again to get a session verified with your code. Workspace administration requires it.</p>
                </div>
            )}
            <ErrorAlert error={error} />
        </div>
    );
}
