import { VerificationMethodLabel } from "@/components/research/verification-method-label";
import type { PassageEntry } from "@/lib/api/types";
import { extractorProvider } from "@/lib/literature";

const SOURCE_KIND: Record<string, string> = {
    fulltext: "full text",
    abstract: "abstract",
    researcher_quote: "your quote (not found in stored text)",
};

/** A verbatim passage with its locator, source kind and how it was extracted. */
export function PassageQuote({ passage, compact = false }: { passage: PassageEntry; compact?: boolean }) {
    const loc = passage.locator ?? {};
    const where = [
        loc.section && `Section: ${loc.section}`,
        loc.page != null && `Page ${loc.page}`,
        loc.char_start != null && `chars ${loc.char_start}–${loc.char_end}`,
    ].filter(Boolean);
    return (
        <figure data-testid="passage" data-verified={passage.verified_in_source ? "true" : "false"} className="flex flex-col gap-1">
            <blockquote className="border-l-2 border-brand pl-3 font-display text-sm text-secondary italic">“{passage.quote}”</blockquote>
            <figcaption className="flex flex-wrap items-center gap-2 text-xs text-tertiary">
                <span>
                    {passage.role} · {SOURCE_KIND[passage.source_kind] ?? passage.source_kind}
                    {where.length ? ` · ${where.join(" · ")}` : ""}
                </span>
                <span className={passage.verified_in_source ? "text-success-primary" : "text-warning-primary"}>
                    {passage.verified_in_source ? "Found verbatim in the source" : "Not verified in the source"}
                </span>
                {!compact && <VerificationMethodLabel method={passage.extraction_method} provider={extractorProvider(passage.extracted_by, passage.extraction_method)} />}
            </figcaption>
            {!compact && passage.summary && <p className="text-xs text-tertiary">Summary: {passage.summary}</p>}
        </figure>
    );
}
