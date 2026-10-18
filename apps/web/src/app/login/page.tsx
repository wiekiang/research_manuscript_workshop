"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { ErrorAlert } from "@/components/research/error-alert";
import { AuthFrame } from "@/components/shell/auth-frame";
import { ApiError, api } from "@/lib/api/client";
import type { TokenBody } from "@/lib/api/types";
import { useSession } from "@/providers/session";

// Local development convenience: a demo account read from the git-ignored apps/web/.env.local.
// Never rendered in a production build, so no credentials ship with the product.
const DEMO =
    process.env.NODE_ENV !== "production" && process.env.NEXT_PUBLIC_DEMO_EMAIL && process.env.NEXT_PUBLIC_DEMO_PASSWORD
        ? { email: process.env.NEXT_PUBLIC_DEMO_EMAIL, password: process.env.NEXT_PUBLIC_DEMO_PASSWORD }
        : null;

function LoginForm() {
    const router = useRouter();
    const params = useSearchParams();
    const { refresh } = useSession();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [totp, setTotp] = useState("");
    const [needsCode, setNeedsCode] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        setError(undefined);
        try {
            await api.post<TokenBody>("/v1/auth/login", { email, password, totp_code: totp || null });
            const me = await refresh();
            const next = params.get("next");
            router.push(me && !me.user.responsibility_acknowledged ? "/onboarding" : next && next.startsWith("/") ? next : "/dashboard");
        } catch (err) {
            if (err instanceof ApiError && err.code === "mfa_required") {
                setNeedsCode(true);
            } else {
                setError(err);
            }
        } finally {
            setBusy(false);
        }
    };

    return (
        <AuthFrame
            title="Sign in"
            description="Use the account you created for your research workspace."
            footer={
                <>
                    New here?{" "}
                    <a className="font-semibold text-brand-secondary underline" href="/register">
                        Create an account
                    </a>
                </>
            }
        >
            <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
                <Input label="Email" type="email" name="email" autoComplete="email" isRequired value={email} onChange={setEmail} />
                <Input label="Password" type="password" name="password" autoComplete="current-password" isRequired value={password} onChange={setPassword} />
                {needsCode && (
                    <Input
                        label="Authentication code"
                        name="totp"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        hint="Enter the 6-digit code from your authenticator app."
                        isRequired
                        value={totp}
                        onChange={setTotp}
                        autoFocus
                    />
                )}
                <ErrorAlert error={error} />
                <Button type="submit" size="lg" isLoading={busy}>
                    {needsCode ? "Verify and sign in" : "Sign in"}
                </Button>
            </form>
            {DEMO && (
                <div className="mt-6 rounded-xl border border-secondary bg-secondary p-4" data-testid="demo-account">
                    <p className="text-sm font-semibold text-primary">Demo account (local development only)</p>
                    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                        <dt className="text-tertiary">Email</dt>
                        <dd className="font-mono text-secondary">{DEMO.email}</dd>
                        <dt className="text-tertiary">Password</dt>
                        <dd className="font-mono text-secondary">{DEMO.password}</dd>
                    </dl>
                    <Button
                        className="mt-3"
                        color="secondary"
                        size="sm"
                        onClick={() => {
                            setEmail(DEMO.email);
                            setPassword(DEMO.password);
                        }}
                    >
                        Use demo account
                    </Button>
                </div>
            )}
        </AuthFrame>
    );
}

export default function LoginPage() {
    return (
        <Suspense>
            <LoginForm />
        </Suspense>
    );
}
