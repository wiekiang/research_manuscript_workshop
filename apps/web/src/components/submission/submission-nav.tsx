"use client";

import { usePathname } from "next/navigation";
import { cx } from "@/utils/cx";

const ITEMS = [
    { seg: "", label: "Readiness" },
    { seg: "authors", label: "Authors" },
    { seg: "disclosures", label: "Disclosures & AI policy" },
    { seg: "eligibility", label: "Deadline eligibility" },
    { seg: "approval", label: "Final approval (H4)" },
    { seg: "packages", label: "Export packages" },
];

/** Sub-navigation of the submission-preparation workspace. There is deliberately no "submit" step. */
export function SubmissionNav({ projectId }: { projectId: string }) {
    const pathname = usePathname() ?? "";
    const current = pathname.split("/")[4] ?? "";
    return (
        <nav aria-label="Submission preparation" className="-mx-1 overflow-x-auto">
            <ul className="flex min-w-max gap-1 px-1">
                {ITEMS.map((i) => {
                    const active = current === i.seg;
                    return (
                        <li key={i.seg || "overview"}>
                            <a
                                href={`/projects/${projectId}/submission${i.seg ? `/${i.seg}` : ""}`}
                                aria-current={active ? "page" : undefined}
                                className={cx(
                                    "block rounded-md px-3 py-1.5 text-sm font-medium outline-focus-ring focus-visible:outline-2",
                                    active ? "bg-brand-primary_alt text-brand-secondary" : "text-tertiary hover:bg-primary_hover hover:text-secondary",
                                )}
                            >
                                {i.label}
                            </a>
                        </li>
                    );
                })}
            </ul>
        </nav>
    );
}

export const EXPORT_NOTICE =
    "The platform prepares packages for human export only. It never submits to a venue; you submit through the venue's own system.";
