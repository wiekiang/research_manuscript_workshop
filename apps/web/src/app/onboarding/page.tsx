"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { ErrorAlert } from "@/components/research/error-alert";
import { MfaSetup } from "@/components/research/mfa-setup";
import { Loading } from "@/components/research/page-header";
import { AuthFrame } from "@/components/shell/auth-frame";
import { api } from "@/lib/api/client";
import { COPY } from "@/lib/copy";
import { useSession } from "@/providers/session";

export default function OnboardingPage() {
    const router = useRouter();
    const { me, loading, refresh } = useSession();
    const [accepted, setAccepted] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();

    useEffect(() => {
        if (!loading && !me) router.replace("/login?next=/onboarding");
    }, [loading, me, router]);
    if (!me) return <Loading label="Loading your account" />;
    const acknowledged = me.user.responsibility_acknowledged;

    const acknowledge = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post("/v1/auth/responsibility-ack", { version: me.responsibility.version });
            await refresh();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <AuthFrame title="Before you start" description="Read how responsibility is shared on this platform.">
            <p data-testid="responsibility-message" className="rounded-xl border-l-4 border-utility-amber-400 bg-secondary p-4 text-md text-primary">
                {COPY.responsibility_message}
            </p>
            {!acknowledged ? (
                <div className="flex flex-col gap-4">
                    <Checkbox isSelected={accepted} onChange={setAccepted} label="I understand and accept this responsibility" />
                    <ErrorAlert error={error} />
                    <Button size="lg" isDisabled={!accepted} isLoading={busy} onClick={acknowledge}>
                        Acknowledge and continue
                    </Button>
                </div>
            ) : (
                <div className="flex flex-col gap-5">
                    <p className="text-sm text-success-primary">Acknowledged. The message is shown again on every new project.</p>
                    <div className="flex flex-col gap-2">
                        <h2 className="text-md font-semibold text-primary">Multi-factor authentication (recommended)</h2>
                        <MfaSetup enabled={me.user.mfa_enabled} onEnabled={() => void refresh()} />
                    </div>
                    <Button size="lg" href="/dashboard">
                        Go to the dashboard
                    </Button>
                </div>
            )}
        </AuthFrame>
    );
}
