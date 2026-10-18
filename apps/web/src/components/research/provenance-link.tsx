"use client";

import { useState } from "react";
import { LinkExternal01 } from "@untitledui/icons";
import { api, describeError } from "@/lib/api/client";
import type { Locator } from "@/lib/api/types";
import { shortHash } from "@/lib/format";
import { cx } from "@/utils/cx";

interface ArtifactLinkProps {
    artifactId: string;
    hash?: string | null;
    label?: string;
    className?: string;
}

/** Link to a committed artifact. The download URL is short-lived and issued only after authorization. */
export function ArtifactLink({ artifactId, hash, label, className }: ArtifactLinkProps) {
    const [error, setError] = useState<string>();
    const open = async () => {
        setError(undefined);
        try {
            const { url } = await api.get<{ url: string }>(`/v1/artifacts/${artifactId}/download-url`);
            window.open(url, "_blank", "noopener,noreferrer");
        } catch (err) {
            setError(describeError(err).title);
        }
    };
    return (
        <span className={cx("inline-flex flex-col", className)}>
            <button
                type="button"
                onClick={open}
                className="inline-flex items-center gap-1 rounded text-left text-xs font-medium text-brand-secondary underline-offset-2 outline-focus-ring hover:underline focus-visible:outline-2"
            >
                {label ?? "Artifact"} <span className="font-normal text-tertiary">{shortHash(hash ?? artifactId)}</span>
                <LinkExternal01 className="size-3" aria-hidden="true" />
                <span className="sr-only">(opens a signed download link)</span>
            </button>
            {error && <span className="text-xs text-error-primary">{error}</span>}
        </span>
    );
}

export function LocatorText({ locator }: { locator: Locator | null | undefined }) {
    if (!locator) return <span className="text-xs text-error-primary">No verified location in the source</span>;
    const parts = [locator.section && `Section: ${locator.section}`, locator.page && `Page ${locator.page}`, `chars ${locator.char_start}–${locator.char_end}`].filter(Boolean);
    return <span className="text-xs text-tertiary">{parts.join(" · ")}</span>;
}

export function SourceQuote({ quote, locator }: { quote: string | null | undefined; locator?: Locator | null }) {
    if (!quote) return <span className="text-xs text-tertiary">No quote</span>;
    return (
        <figure className="flex flex-col gap-1">
            <blockquote className="border-l-2 border-brand pl-3 font-display text-sm text-secondary italic">“{quote}”</blockquote>
            <figcaption>
                <LocatorText locator={locator} />
            </figcaption>
        </figure>
    );
}
