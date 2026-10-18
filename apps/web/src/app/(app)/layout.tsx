"use client";

import type { ReactNode } from "react";
import { Loading } from "@/components/research/page-header";
import { AppShell } from "@/components/shell/app-shell";
import { useRequireSession } from "@/providers/session";

export default function AppLayout({ children }: { children: ReactNode }) {
    const { me, loading } = useRequireSession();
    if (loading || !me) {
        return (
            <main id="main-content" className="mx-auto max-w-md p-8">
                <Loading label="Checking your session" />
            </main>
        );
    }
    if (!me.session.tenant_id) {
        return (
            <AppShell>
                <NoWorkspace />
            </AppShell>
        );
    }
    return <AppShell>{children}</AppShell>;
}

function NoWorkspace() {
    return (
        <div className="max-w-xl">
            <h1 className="font-display text-display-xs font-semibold text-primary">Create a workspace to start</h1>
            <p className="mt-2 text-md text-tertiary">Projects belong to a workspace. Create one in settings, or ask a workspace admin to add your account.</p>
            <a className="mt-4 inline-block text-sm font-semibold text-brand-secondary underline" href="/settings">
                Go to settings
            </a>
        </div>
    );
}
