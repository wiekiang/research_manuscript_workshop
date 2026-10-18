import type { ReactNode } from "react";
import { PRODUCT_NAME } from "@/lib/brand";

export function AuthFrame({ title, description, children, footer }: { title: string; description?: ReactNode; children: ReactNode; footer?: ReactNode }) {
    return (
        <div className="flex min-h-dvh flex-col bg-secondary_subtle">
            <header className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-8">
                <a href="/" className="font-display text-lg font-semibold text-primary">
                    {PRODUCT_NAME}
                </a>
            </header>
            <main id="main-content" className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 pb-16">
                <div className="flex flex-col gap-6 rounded-2xl bg-primary p-6 shadow-sm ring-1 ring-secondary sm:p-8">
                    <div className="flex flex-col gap-1">
                        <h1 className="font-display text-display-xs font-semibold text-primary">{title}</h1>
                        {description && <div className="text-md text-tertiary">{description}</div>}
                    </div>
                    {children}
                </div>
                {footer && <div className="mt-4 text-center text-sm text-tertiary">{footer}</div>}
            </main>
        </div>
    );
}
