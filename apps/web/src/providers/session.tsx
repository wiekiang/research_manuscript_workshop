"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ApiError, api } from "@/lib/api/client";
import type { Me } from "@/lib/api/types";

interface SessionValue {
    me: Me | null;
    loading: boolean;
    refresh: () => Promise<Me | null>;
    logout: () => Promise<void>;
    switchWorkspace: (tenantId: string) => Promise<void>;
    currentWorkspace: Me["workspaces"][number] | undefined;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
    const [me, setMe] = useState<Me | null>(null);
    const [loading, setLoading] = useState(true);

    const refresh = useCallback(async () => {
        try {
            const m = await api.get<Me>("/v1/auth/me");
            setMe(m);
            return m;
        } catch (err) {
            if (err instanceof ApiError && err.status === 401) setMe(null);
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void refresh();
    }, [refresh]);

    const logout = useCallback(async () => {
        try {
            await api.post("/v1/auth/logout");
        } finally {
            setMe(null);
        }
    }, []);

    const switchWorkspace = useCallback(
        async (tenantId: string) => {
            await api.post("/v1/auth/switch-workspace", { tenant_id: tenantId });
            await refresh();
        },
        [refresh],
    );

    const value = useMemo<SessionValue>(
        () => ({
            me,
            loading,
            refresh,
            logout,
            switchWorkspace,
            currentWorkspace: me?.workspaces.find((w) => w.tenant_id === me.session.tenant_id),
        }),
        [me, loading, refresh, logout, switchWorkspace],
    );
    return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
    const v = useContext(SessionContext);
    if (!v) throw new Error("useSession must be used inside SessionProvider");
    return v;
}

/** Redirects to /login when signed out, and to /onboarding until the responsibility message is acknowledged. */
export function useRequireSession(): SessionValue {
    const session = useSession();
    const router = useRouter();
    const pathname = usePathname();
    useEffect(() => {
        if (session.loading) return;
        if (!session.me) {
            router.replace(`/login?next=${encodeURIComponent(pathname ?? "/dashboard")}`);
        } else if (!session.me.user.responsibility_acknowledged && pathname !== "/onboarding") {
            router.replace("/onboarding");
        }
    }, [session.loading, session.me, router, pathname]);
    return session;
}
