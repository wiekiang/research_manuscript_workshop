import type { ReactNode } from "react";
import { cx } from "@/utils/cx";

export function PageHeader({ title, description, actions, className }: { title: string; description?: ReactNode; actions?: ReactNode; className?: string }) {
    return (
        <header className={cx("flex flex-col gap-3 border-b border-secondary pb-5 sm:flex-row sm:items-end sm:justify-between", className)}>
            <div className="flex max-w-3xl flex-col gap-1">
                <h1 className="font-display text-display-xs font-semibold text-primary">{title}</h1>
                {description && <div className="text-md text-tertiary">{description}</div>}
            </div>
            {actions && <div className="flex flex-wrap gap-3">{actions}</div>}
        </header>
    );
}

export function Section({ title, description, children, actions, id, className }: { title: string; description?: ReactNode; children: ReactNode; actions?: ReactNode; id?: string; className?: string }) {
    const headingId = id ?? `section-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    return (
        <section aria-labelledby={headingId} className={cx("flex flex-col gap-4", className)}>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div className="flex flex-col gap-0.5">
                    <h2 id={headingId} className="font-display text-lg font-semibold text-primary">
                        {title}
                    </h2>
                    {description && <div className="max-w-prose text-sm text-tertiary">{description}</div>}
                </div>
                {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
            </div>
            {children}
        </section>
    );
}

export function Loading({ label = "Loading" }: { label?: string }) {
    return (
        <p role="status" className="flex items-center gap-2 py-6 text-sm text-tertiary">
            <span className="size-4 animate-spin rounded-full border-2 border-secondary border-t-brand motion-reduce:animate-none" aria-hidden="true" />
            {label}…
        </p>
    );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-0.5">
            <dt className="text-xs text-tertiary">{label}</dt>
            <dd className="text-sm text-primary">{children}</dd>
        </div>
    );
}
