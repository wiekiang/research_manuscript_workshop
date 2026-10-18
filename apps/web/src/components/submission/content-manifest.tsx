"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { ArtifactLink } from "@/components/research/provenance-link";
import { ApiError, api } from "@/lib/api/client";
import type { ContentManifestView, FinalApprovalResult } from "@/lib/api/types";
import { humanize, shortHash } from "@/lib/format";
import { STATE_LABEL } from "@/lib/states";

export function ManifestItems({ view }: { view: ContentManifestView }) {
    return (
        <table data-testid="content-manifest" className="w-full text-left text-sm">
            <thead>
                <tr className="border-b border-secondary text-xs text-tertiary">
                    <th className="py-2 pr-3 font-medium">Role</th>
                    <th className="py-2 pr-3 font-medium">Path in package</th>
                    <th className="py-2 pr-3 font-medium">SHA-256</th>
                    <th className="py-2 font-medium">Artifact</th>
                </tr>
            </thead>
            <tbody>
                {view.items.map((i) => (
                    <tr key={`${i.role}-${i.path}`} data-testid="manifest-item" data-role={i.role} className="border-b border-secondary">
                        <td className="py-2 pr-3 text-primary">{humanize(i.role)}</td>
                        <td className="py-2 pr-3 font-mono text-xs text-secondary">{i.path}</td>
                        <td className="py-2 pr-3 font-mono text-xs text-secondary" title={i.sha256}>
                            {shortHash(i.sha256, 16)}
                        </td>
                        <td className="py-2">
                            <ArtifactLink artifactId={i.artifact_id} hash={i.sha256} label={i.kind} />
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

/**
 * H4: the corresponding author signs the frozen content manifest. The server re-checks the pre-approval readiness
 * assessment and every author's assent to this exact version.
 */
export function FinalApprovalForm({ view, projectId, inFinalApproval, onSigned }: { view: ContentManifestView; projectId: string; inFinalApproval: boolean; onSigned: (r: FinalApprovalResult) => void }) {
    const [accepted, setAccepted] = useState(false);
    const [rationale, setRationale] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const forbidden = error instanceof ApiError && error.status === 403;
    return (
        <div className="flex flex-col gap-3">
            <blockquote data-testid="h4-declaration" className="rounded-xl bg-secondary p-4 text-sm text-primary">
                {view.declaration}
            </blockquote>
            <TextArea label="Rationale (optional)" value={rationale} onChange={setRationale} rows={2} />
            <Checkbox isSelected={accepted} onChange={setAccepted} label="I have read this declaration and it is true for me" />
            {!inFinalApproval && <p className="text-sm text-tertiary">H4 is signed when the project is in {STATE_LABEL.FINAL_APPROVAL}.</p>}
            <ErrorAlert error={error} />
            {forbidden && <p className="text-sm text-tertiary">Only the corresponding author named in the author record can sign H4.</p>}
            <div>
                <Button
                    size="sm"
                    isLoading={busy}
                    isDisabled={!accepted}
                    onClick={async () => {
                        setBusy(true);
                        setError(undefined);
                        try {
                            onSigned(
                                await api.post<FinalApprovalResult>(`/v1/projects/${projectId}/final-approval`, {
                                    declaration_accepted: accepted,
                                    declaration_text: view.declaration,
                                    rationale: rationale.trim() || null,
                                }),
                            );
                        } catch (err) {
                            setError(err);
                        } finally {
                            setBusy(false);
                        }
                    }}
                >
                    Sign final approval (H4)
                </Button>
            </div>
        </div>
    );
}
