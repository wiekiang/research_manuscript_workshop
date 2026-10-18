"use client";

import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import type { ExportPackageEntry } from "@/lib/api/types";
import { formatDateTime, shortHash } from "@/lib/format";
import { PACKAGE_STATUS_LABEL, packageLabel, packageStatusKey } from "@/lib/submission";

/** One export package. Unapproved packages are labelled prominently; stale packages are kept for audit. */
export function PackageCard({ p }: { p: ExportPackageEntry }) {
    return (
        <article data-testid="package" data-approved={p.approved} data-status={p.status} className="flex flex-col gap-3 rounded-xl border border-secondary p-4">
            <div className="flex flex-wrap items-center gap-2">
                <StatusBadge status={p.approved ? "package_approved" : "package_unapproved"} label={packageLabel(p)} size="md" />
                <StatusBadge status={packageStatusKey(p.status)} label={PACKAGE_STATUS_LABEL[p.status] ?? p.status} />
                {p.stale && <StatusBadge status="stale" label="Stale" />}
                <span className="text-xs text-tertiary">{formatDateTime(p.created_at)}</span>
            </div>
            {p.name && <p className="font-mono text-xs text-secondary">{p.name}</p>}
            {p.stale && <p data-testid="package-stale" className="text-sm text-secondary">No longer current: {p.stale}</p>}
            {p.problems.length > 0 && (
                <ul data-testid="package-problems" className="list-disc pl-5 text-sm text-error-primary">
                    {p.problems.map((x) => (
                        <li key={x}>{x}</li>
                    ))}
                </ul>
            )}
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <div>
                    <dt className="text-xs text-tertiary">Package checksum (SHA-256)</dt>
                    <dd className="font-mono text-xs break-all text-primary">{p.checksum ?? "not built yet"}</dd>
                </div>
                <div>
                    <dt className="text-xs text-tertiary">Signed content manifest</dt>
                    <dd className="font-mono text-xs break-all text-primary">{p.content_manifest_hash ?? "none (not signed at H4)"}</dd>
                </div>
            </dl>
            {p.files.length > 0 && (
                <details>
                    <summary className="cursor-pointer text-sm text-secondary">{p.files.length} files with hashes</summary>
                    <ul className="mt-2 flex flex-col gap-1 text-xs">
                        {p.files.map((f) => (
                            <li key={f.path} className="flex flex-wrap gap-2">
                                <span className="font-mono text-secondary">{f.path}</span>
                                <span className="font-mono text-tertiary" title={f.sha256}>
                                    {shortHash(f.sha256, 16)}
                                </span>
                            </li>
                        ))}
                    </ul>
                </details>
            )}
            {p.artifact_id && <ArtifactLink artifactId={p.artifact_id} hash={p.checksum} label="Download package (for your own export)" />}
        </article>
    );
}
