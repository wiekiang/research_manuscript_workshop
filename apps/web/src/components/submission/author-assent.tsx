"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { AuthorEntry, AuthorsView } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { CREDIT_LABEL } from "@/lib/submission";

export function assentStatusKey(a: AuthorEntry): string {
    if (!a.assent) return "assent_missing";
    return a.assent.method === "in_product" ? "assent_given" : "assent_offline";
}

function AssentDialog({ isOpen, onOpenChange, title, statement, needsEvidence, path, onDone }: {
    isOpen: boolean;
    onOpenChange: (o: boolean) => void;
    title: string;
    statement: string;
    needsEvidence: boolean;
    path: string;
    onDone: () => void;
}) {
    const [accepted, setAccepted] = useState(false);
    const [evidence, setEvidence] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <DialogShell
            isOpen={isOpen}
            onOpenChange={onOpenChange}
            title={title}
            footer={
                <>
                    <Button color="secondary" size="sm" onClick={() => onOpenChange(false)}>
                        Close
                    </Button>
                    <Button
                        size="sm"
                        isLoading={busy}
                        isDisabled={!accepted}
                        onClick={async () => {
                            setBusy(true);
                            setError(undefined);
                            try {
                                await api.post(path, { statement_accepted: accepted, statement_text: statement, evidence: evidence.trim() || null });
                                onDone();
                                onOpenChange(false);
                            } catch (err) {
                                setError(err);
                            } finally {
                                setBusy(false);
                            }
                        }}
                    >
                        Record approval
                    </Button>
                </>
            }
        >
            <blockquote data-testid="assent-statement" className="rounded-xl bg-secondary p-4 text-sm text-primary">
                {statement}
            </blockquote>
            {needsEvidence && (
                <TextArea
                    label="Evidence of the author's explicit approval"
                    hint="For example: the date and sender of the approving e-mail. Silence or an invitation is not assent."
                    value={evidence}
                    onChange={setEvidence}
                    rows={3}
                />
            )}
            <Checkbox isSelected={accepted} onChange={setAccepted} label="This statement is true" />
            <ErrorAlert error={error} />
        </DialogShell>
    );
}

/**
 * Current author record with each author's assent to the current manuscript version. An author approves in the
 * product; the corresponding author may record an offline attestation with evidence. Assent is never inferred.
 */
export function AuthorRoster({ view, projectId, myUserId, iAmCorresponding, onChanged }: {
    view: AuthorsView;
    projectId: string;
    myUserId: string | undefined;
    iAmCorresponding: boolean;
    onChanged: () => void;
}) {
    const [open, setOpen] = useState<{ author: AuthorEntry; mode: "self" | "offline" } | null>(null);
    if (view.authors.length === 0) return <p data-testid="authors-empty" className="text-sm text-tertiary">No author record has been saved yet.</p>;
    return (
        <>
            {view.manuscript_version == null && (
                <p className="text-sm text-tertiary">There is no manuscript version yet, so authors cannot approve a version.</p>
            )}
            <ol className="flex flex-col gap-3">
                {view.authors.map((a) => (
                    <li key={a.id} data-testid="author-entry" className="flex flex-col gap-2 rounded-xl border border-secondary p-4">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs text-tertiary">{a.position}.</span>
                            <span className="text-sm font-semibold text-primary">{a.name}</span>
                            {a.corresponding && <StatusBadge status="complete" label="Corresponding author" />}
                            <StatusBadge status={assentStatusKey(a)} />
                            {a.assent && <span className="text-xs text-tertiary">{formatDateTime(a.assent.at)}</span>}
                        </div>
                        <p className="text-sm text-secondary">{[a.email, a.affiliations.join("; "), a.orcid && `ORCID ${a.orcid}`].filter(Boolean).join(" · ")}</p>
                        <p className="text-sm text-secondary">
                            <span className="text-tertiary">Roles:</span> {a.contribution_roles.map((r) => CREDIT_LABEL[r] ?? r).join(", ")}
                        </p>
                        <p className="text-sm text-secondary">
                            <span className="text-tertiary">Contribution:</span> {a.contribution_statement}
                        </p>
                        <p className="text-sm text-secondary">
                            <span className="text-tertiary">Competing interests:</span> {a.competing_interests} · <span className="text-tertiary">Funding:</span> {a.funding}
                        </p>
                        {a.assent?.evidence && <p className="text-xs text-tertiary">Evidence recorded: {a.assent.evidence}</p>}
                        {view.manuscript_version != null && !a.assent && (
                            <div className="flex flex-wrap gap-2">
                                {a.user_id && a.user_id === myUserId && (
                                    <Button size="sm" onClick={() => setOpen({ author: a, mode: "self" })}>
                                        Approve manuscript version {view.manuscript_version}
                                    </Button>
                                )}
                                {iAmCorresponding && a.user_id !== myUserId && (
                                    <Button size="sm" color="secondary" onClick={() => setOpen({ author: a, mode: "offline" })}>
                                        Record offline attestation
                                    </Button>
                                )}
                            </div>
                        )}
                    </li>
                ))}
            </ol>
            {open && (
                <AssentDialog
                    isOpen
                    onOpenChange={(o) => !o && setOpen(null)}
                    title={open.mode === "self" ? `Approve manuscript version ${view.manuscript_version}` : `Offline attestation for ${open.author.name}`}
                    statement={open.mode === "self" ? view.author_approval_text : view.offline_attestation_text}
                    needsEvidence={open.mode === "offline"}
                    path={`/v1/projects/${projectId}/authors/${open.author.id}/approve`}
                    onDone={onChanged}
                />
            )}
        </>
    );
}
