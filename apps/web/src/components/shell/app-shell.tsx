"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Bell01, BookOpen01, FilePlus02, LayoutAlt01, LogOut01, Menu02, Moon01, Settings01, Signal01, Sun, XClose } from "@untitledui/icons";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { NavItemBase } from "@/components/application/app-navigation/base-components/nav-item";
import { Button } from "@/components/base/buttons/button";
import { NativeSelect } from "@/components/base/select/select-native";
import { useResource } from "@/hooks/use-resource";
import type { Notification } from "@/lib/api/types";
import { useSession } from "@/providers/session";
import { cx } from "@/utils/cx";
import { PRODUCT_NAME } from "@/lib/brand";

const NAV = [
    { label: "Dashboard", href: "/dashboard", icon: LayoutAlt01 },
    { label: "New project", href: "/projects/new", icon: FilePlus02 },
    { label: "Conferences", href: "/conferences", icon: Signal01 },
    { label: "Notifications", href: "/notifications", icon: Bell01 },
    { label: "Settings", href: "/settings", icon: Settings01 },
];

export function Wordmark({ className }: { className?: string }) {
    return (
        <a href="/dashboard" className={cx("flex items-center gap-2 rounded-md outline-focus-ring focus-visible:outline-2", className)}>
            <BookOpen01 className="size-6 text-fg-brand-primary" aria-hidden="true" />
            <span className="font-display text-lg font-semibold text-primary">{PRODUCT_NAME}</span>
        </a>
    );
}

function ThemeToggle() {
    const { resolvedTheme, setTheme } = useTheme();
    const [mounted, setMounted] = useState(false);
    useEffect(() => setMounted(true), []);
    if (!mounted) return null;
    const dark = resolvedTheme === "dark";
    return (
        <Button color="tertiary" size="sm" iconLeading={dark ? Sun : Moon01} onClick={() => setTheme(dark ? "light" : "dark")}>
            {dark ? "Light theme" : "Dark theme"}
        </Button>
    );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
    const pathname = usePathname() ?? "";
    const router = useRouter();
    const { me, logout, switchWorkspace, currentWorkspace } = useSession();
    const { data: notes } = useResource<{ items: Notification[] }>(me ? "/v1/notifications?unread_only=true" : null, 30000);
    const unread = notes?.items.length ?? 0;

    return (
        <div className="flex h-full flex-col justify-between gap-6 p-4">
            <div className="flex flex-col gap-6">
                <Wordmark />
                {me && me.workspaces.length > 0 && (
                    <NativeSelect
                        size="sm"
                        label="Workspace"
                        value={currentWorkspace?.tenant_id ?? ""}
                        onChange={async (e) => {
                            await switchWorkspace(e.target.value);
                            router.push("/dashboard");
                        }}
                        options={me.workspaces.map((w) => ({ label: `${w.name}${w.role === "workspace_admin" ? " (admin)" : ""}`, value: w.tenant_id }))}
                    />
                )}
                <nav aria-label="Main">
                    <ul className="flex flex-col gap-0.5">
                        {NAV.map((item) => (
                            <li key={item.href} onClick={onNavigate}>
                                <NavItemBase
                                    type="link"
                                    href={item.href}
                                    icon={item.icon}
                                    current={pathname === item.href || (item.href === "/dashboard" && pathname.startsWith("/projects/") && !pathname.startsWith("/projects/new"))}
                                    badge={item.href === "/notifications" && unread > 0 ? String(unread) : undefined}
                                >
                                    {item.label}
                                    {item.href === "/notifications" && unread > 0 && <span className="sr-only"> ({unread} unread)</span>}
                                </NavItemBase>
                            </li>
                        ))}
                    </ul>
                </nav>
            </div>
            <div className="flex flex-col gap-3 border-t border-secondary pt-4">
                <ThemeToggle />
                {me && (
                    <div className="flex flex-col gap-2">
                        <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-primary">{me.user.display_name}</p>
                            <p className="truncate text-xs text-tertiary">{me.user.email}</p>
                        </div>
                        <Button
                            color="secondary"
                            size="sm"
                            iconLeading={LogOut01}
                            onClick={async () => {
                                await logout();
                                router.push("/login");
                            }}
                        >
                            Sign out
                        </Button>
                    </div>
                )}
            </div>
        </div>
    );
}

export function AppShell({ children }: { children: ReactNode }) {
    const [open, setOpen] = useState(false);
    const pathname = usePathname();
    useEffect(() => setOpen(false), [pathname]);
    // After a client-side navigation the element that had focus is often gone, and the browser's sequential focus
    // starting point stays where it was. Reset it to the top of the page (as a full page load would) so the next
    // Tab reaches the skip link first.
    useEffect(() => {
        if (typeof document === "undefined") return;
        const active = document.activeElement;
        if (!active || active === document.body) {
            const anchor = document.getElementById("focus-reset");
            anchor?.focus({ preventScroll: true });
            anchor?.blur();
        }
    }, [pathname]);

    return (
        <div className="flex min-h-dvh bg-secondary_subtle">
            <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 border-r border-secondary bg-primary lg:block">
                <SidebarContent />
            </aside>
            <div className="flex min-w-0 flex-1 flex-col">
                <header className="flex items-center justify-between border-b border-secondary bg-primary px-4 py-3 lg:hidden">
                    <Wordmark />
                    <Button color="tertiary" size="sm" iconLeading={open ? XClose : Menu02} onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="mobile-nav">
                        {open ? "Close menu" : "Menu"}
                    </Button>
                </header>
                {open && (
                    <div id="mobile-nav" className="border-b border-secondary bg-primary lg:hidden">
                        <SidebarContent onNavigate={() => setOpen(false)} />
                    </div>
                )}
                <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 outline-none sm:px-6 lg:px-8 lg:py-8">
                    {children}
                </main>
            </div>
        </div>
    );
}
