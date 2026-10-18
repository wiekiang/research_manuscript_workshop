"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { ErrorAlert } from "@/components/research/error-alert";
import { AuthFrame } from "@/components/shell/auth-frame";
import { api } from "@/lib/api/client";
import type { TokenBody } from "@/lib/api/types";
import { useSession } from "@/providers/session";

export default function RegisterPage() {
    const router = useRouter();
    const { refresh } = useSession();
    const [form, setForm] = useState({ display_name: "", email: "", password: "", workspace_name: "" });
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        setError(undefined);
        try {
            await api.post<TokenBody>("/v1/auth/register", { ...form, workspace_name: form.workspace_name || null });
            await refresh();
            router.push("/onboarding");
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <AuthFrame
            title="Create your account"
            description="You will set up a workspace for your projects and coauthors."
            footer={
                <>
                    Already registered?{" "}
                    <a className="font-semibold text-brand-secondary underline" href="/login">
                        Sign in
                    </a>
                </>
            }
        >
            <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
                <Input label="Your name" name="display_name" autoComplete="name" isRequired value={form.display_name} onChange={set("display_name")} />
                <Input label="Email" type="email" name="email" autoComplete="email" isRequired value={form.email} onChange={set("email")} />
                <Input
                    label="Password"
                    type="password"
                    name="password"
                    autoComplete="new-password"
                    isRequired
                    hint="At least 12 characters, mixing upper- and lower-case letters and a digit."
                    value={form.password}
                    onChange={set("password")}
                />
                <Input label="Workspace name" name="workspace_name" hint="For example your lab or research group." isRequired value={form.workspace_name} onChange={set("workspace_name")} />
                <ErrorAlert error={error} />
                <Button type="submit" size="lg" isLoading={busy}>
                    Create account
                </Button>
            </form>
        </AuthFrame>
    );
}
