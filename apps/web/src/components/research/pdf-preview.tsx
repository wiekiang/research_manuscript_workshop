"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { api, describeError } from "@/lib/api/client";

/**
 * Inline preview of a committed PDF artifact. The signed URL is short-lived and requested only when the preview is
 * opened, after authorization. A download link is always offered because some browsers block inline PDFs.
 */
export function PdfPreview({ artifactId, title }: { artifactId: string; title: string }) {
    const [open, setOpen] = useState(false);
    const [url, setUrl] = useState<string>();
    const [error, setError] = useState<string>();

    useEffect(() => {
        if (!open || url) return;
        let cancelled = false;
        api.get<{ url: string }>(`/v1/artifacts/${artifactId}/download-url`)
            .then((r) => !cancelled && setUrl(r.url))
            .catch((err) => !cancelled && setError(describeError(err).title));
        return () => {
            cancelled = true;
        };
    }, [open, url, artifactId]);

    return (
        <div className="flex flex-col gap-2" data-testid="pdf-preview">
            <div className="flex flex-wrap gap-2">
                <Button color="secondary" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
                    {open ? "Hide PDF preview" : "Preview PDF"}
                </Button>
                {url && (
                    <Button color="link-color" size="sm" href={url} target="_blank" rel="noopener noreferrer">
                        Download PDF
                    </Button>
                )}
            </div>
            {error && <p className="text-xs text-error-primary">{error}</p>}
            {open && url && (
                <object data={url} type="application/pdf" aria-label={title} className="h-[32rem] w-full rounded-lg ring-1 ring-secondary">
                    <p className="p-4 text-sm text-tertiary">
                        Your browser cannot show PDFs inline.{" "}
                        <a href={url} target="_blank" rel="noopener noreferrer" className="text-brand-secondary underline">
                            Download the PDF
                        </a>
                        .
                    </p>
                </object>
            )}
        </div>
    );
}
