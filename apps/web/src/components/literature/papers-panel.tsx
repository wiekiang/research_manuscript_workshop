"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { PaperEntry, PassageEntry } from "@/lib/api/types";
import { fulltextLabel, identityLabel } from "@/lib/literature";

export function IdentityBadge({ paper }: { paper: Pick<PaperEntry, "identity_status" | "identity_verification"> }) {
    const l = identityLabel(paper.identity_status, paper.identity_verification);
    return (
        <span className="flex flex-col gap-0.5">
            <StatusBadge status={l.status} label={l.label} />
            <span className="text-xs text-tertiary">{l.detail}</span>
        </span>
    );
}

export function FulltextBadge({ paper }: { paper: PaperEntry }) {
    const l = fulltextLabel(paper);
    return (
        <span className="flex flex-col gap-0.5">
            <StatusBadge status={l.status} label={l.label} />
            {l.detail && <span className="text-xs text-tertiary">{l.detail}</span>}
            {paper.identity_verification?.fulltext_detail && <span className="text-xs text-tertiary">{paper.identity_verification.fulltext_detail}</span>}
        </span>
    );
}

type DialogKind = { kind: "screen" | "notes" | "passage"; paper: PaperEntry } | { kind: "add" | "upload" } | null;

export function PapersPanel({
    projectId,
    papers,
    canEdit,
    onChanged,
    filter,
}: {
    projectId: string;
    papers: PaperEntry[];
    canEdit: boolean;
    onChanged: () => void;
    filter?: string | null;
}) {
    const [dialog, setDialog] = useState<DialogKind>(null);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [error, setError] = useState<unknown>();
    const shown = papers.filter((p) => matchesFilter(p, filter));
    return (
        <Section
            id="papers"
            title="Papers"
            description="Identity is checked deterministically against Crossref or DataCite. A verified identity does not mean a paper supports any claim. Full text is stored only when the item licence permits it."
            actions={
                canEdit && (
                    <>
                        <Button size="sm" color="secondary" onClick={() => setDialog({ kind: "add" })}>
                            Add citation
                        </Button>
                        <Button size="sm" color="secondary" onClick={() => setDialog({ kind: "upload" })}>
                            Upload paper
                        </Button>
                    </>
                )
            }
        >
            {filter && (
                <p className="text-sm text-tertiary">
                    Showing papers matching “{FILTER_LABELS[filter] ?? filter}” ({shown.length} of {papers.length}).{" "}
                    <a className="underline" href="?">
                        Show all
                    </a>
                </p>
            )}
            <ErrorAlert error={error} />
            {papers.length === 0 && <p className="text-sm text-tertiary">No papers yet. Run a search, add a citation or upload a paper you have the right to use.</p>}
            <ul className="flex flex-col gap-3">
                {shown.map((p) => (
                    <li key={p.id} data-testid="paper-row" data-identity={p.identity_status} data-fulltext={p.fulltext_status} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                        <div className="flex flex-col gap-1">
                            <p className="font-medium text-primary">{p.title}</p>
                            <p className="text-xs text-tertiary">
                                {p.authors.slice(0, 6).join(", ")}
                                {p.authors.length > 6 ? " et al." : ""}
                                {p.year ? ` · ${p.year}` : ""}
                                {p.venue ? ` · ${p.venue}` : ""} · added via {p.origin} · sources: {p.sources.join(", ") || "—"}
                            </p>
                            {p.doi && (
                                <a className="text-xs text-brand-secondary underline-offset-2 hover:underline" href={`https://doi.org/${p.doi}`} target="_blank" rel="noreferrer">
                                    doi:{p.doi}
                                </a>
                            )}
                        </div>
                        <div className="grid gap-3 sm:grid-cols-3">
                            <div>
                                <p className="text-xs font-medium text-secondary">Identity</p>
                                <IdentityBadge paper={p} />
                            </div>
                            <div>
                                <p className="text-xs font-medium text-secondary">Full text</p>
                                <FulltextBadge paper={p} />
                            </div>
                            <div>
                                <p className="text-xs font-medium text-secondary">Screening</p>
                                {p.screening.length === 0 ? (
                                    <span className="text-xs text-tertiary">Not screened</span>
                                ) : (
                                    p.screening.map((s) => (
                                        <p key={s.stage} className="text-xs text-secondary">
                                            {s.stage.replace("_", "/")}: <strong>{s.decision}</strong> — {s.reason} ({s.method})
                                        </p>
                                    ))
                                )}
                            </div>
                        </div>
                        {p.notes && <p className="rounded-md bg-secondary px-2 py-1 text-xs text-secondary">Private note: {p.notes}</p>}
                        {canEdit && (
                            <div className="flex flex-wrap gap-2">
                                {["none", "located", "inaccessible"].includes(p.fulltext_status) && (
                                    <Button
                                        size="xs"
                                        color="secondary"
                                        isLoading={busyId === p.id}
                                        onClick={async () => {
                                            setBusyId(p.id);
                                            setError(undefined);
                                            try {
                                                await api.post(`/v1/projects/${projectId}/papers/${p.id}/fulltext`, {});
                                                onChanged();
                                            } catch (err) {
                                                setError(err);
                                            } finally {
                                                setBusyId(null);
                                            }
                                        }}
                                    >
                                        Request permitted full text
                                    </Button>
                                )}
                                <Button size="xs" color="secondary" onClick={() => setDialog({ kind: "screen", paper: p })}>
                                    Screen
                                </Button>
                                <Button size="xs" color="secondary" onClick={() => setDialog({ kind: "notes", paper: p })}>
                                    Private notes
                                </Button>
                                <Button size="xs" color="secondary" onClick={() => setDialog({ kind: "passage", paper: p })}>
                                    Add passage
                                </Button>
                            </div>
                        )}
                    </li>
                ))}
            </ul>
            {dialog?.kind === "add" && <AddCitationDialog projectId={projectId} onClose={() => setDialog(null)} onDone={onChanged} />}
            {dialog?.kind === "upload" && <UploadPaperDialog projectId={projectId} onClose={() => setDialog(null)} onDone={onChanged} />}
            {dialog?.kind === "screen" && <ScreenDialog projectId={projectId} paper={dialog.paper} onClose={() => setDialog(null)} onDone={onChanged} />}
            {dialog?.kind === "notes" && <NotesDialog projectId={projectId} paper={dialog.paper} onClose={() => setDialog(null)} onDone={onChanged} />}
            {dialog?.kind === "passage" && <PassageDialog projectId={projectId} paper={dialog.paper} onClose={() => setDialog(null)} onDone={onChanged} />}
        </Section>
    );
}

export const FILTER_LABELS: Record<string, string> = {
    fulltext: "full text reviewed",
    abstract: "abstract only",
    metadata: "metadata only",
    inaccessible: "full text inaccessible or not permitted",
    excluded: "excluded in screening",
    included: "included in screening",
    screened: "screened",
    identity_problem: "identity problems",
    identity_verified: "identity verified",
    manual: "added manually or uploaded",
};

export function matchesFilter(p: PaperEntry, filter: string | null | undefined): boolean {
    switch (filter) {
        case null:
        case undefined:
        case "":
            return true;
        case "fulltext":
            return p.fulltext_status === "parsed";
        case "abstract":
            return p.fulltext_status !== "parsed" && !!p.abstract;
        case "metadata":
            return p.fulltext_status !== "parsed" && !p.abstract;
        case "inaccessible":
            return ["not_permitted", "inaccessible"].includes(p.fulltext_status);
        case "excluded":
            return p.screening.some((s) => s.decision === "exclude");
        case "included":
            return p.screening.some((s) => s.decision === "include");
        case "screened":
            return p.screening.length > 0;
        case "identity_problem":
            return ["mismatch", "not_found"].includes(p.identity_status);
        case "identity_verified":
            return p.identity_status === "verified";
        case "manual":
            return ["manual", "upload"].includes(p.origin);
        default:
            return true;
    }
}

function useSubmit(onDone: () => void, onClose: () => void) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    async function run(fn: () => Promise<unknown>) {
        setBusy(true);
        setError(undefined);
        try {
            await fn();
            onDone();
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    }
    return { busy, error, run };
}

function AddCitationDialog({ projectId, onClose, onDone }: { projectId: string; onClose: () => void; onDone: () => void }) {
    const [doi, setDoi] = useState("");
    const [title, setTitle] = useState("");
    const [authors, setAuthors] = useState("");
    const [year, setYear] = useState("");
    const [venue, setVenue] = useState("");
    const s = useSubmit(onDone, onClose);
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Add a citation"
            description="Enter a DOI or the bibliographic details. The identity stays unverified until a deterministic registry lookup confirms it."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        isLoading={s.busy}
                        isDisabled={!doi.trim() && !title.trim()}
                        onClick={() =>
                            s.run(() =>
                                api.post(`/v1/projects/${projectId}/papers`, {
                                    doi: doi.trim() || null,
                                    title: title.trim() || null,
                                    authors: authors.split(";").map((a) => a.trim()).filter(Boolean),
                                    year: year ? Number(year) : null,
                                    venue: venue.trim() || null,
                                }),
                            )
                        }
                    >
                        Add citation
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <Input label="DOI" value={doi} onChange={setDoi} placeholder="10.xxxx/…" />
                <Input label="Title" value={title} onChange={setTitle} />
                <Input label="Authors (separate with ;)" value={authors} onChange={setAuthors} />
                <div className="grid gap-3 sm:grid-cols-2">
                    <Input label="Year" inputMode="numeric" value={year} onChange={setYear} />
                    <Input label="Venue" value={venue} onChange={setVenue} />
                </div>
                <ErrorAlert error={s.error} />
            </div>
        </DialogShell>
    );
}

function UploadPaperDialog({ projectId, onClose, onDone }: { projectId: string; onClose: () => void; onDone: () => void }) {
    const [file, setFile] = useState<File | null>(null);
    const [doi, setDoi] = useState("");
    const [title, setTitle] = useState("");
    const [rights, setRights] = useState("");
    const [attest, setAttest] = useState(false);
    const s = useSubmit(onDone, onClose);
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Upload a paper"
            description="Upload only papers you have the right to use for this project. The file is scanned, stored privately for this project and parsed for verbatim passages."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button
                        isLoading={s.busy}
                        isDisabled={!file || !attest || rights.trim().length < 10}
                        onClick={() =>
                            s.run(() => {
                                const fd = new FormData();
                                fd.append("file", file as File);
                                if (doi.trim()) fd.append("doi", doi.trim());
                                if (title.trim()) fd.append("title", title.trim());
                                fd.append("rights_statement", rights);
                                fd.append("attest_rights", attest ? "true" : "false");
                                return api.post(`/v1/projects/${projectId}/papers/upload`, fd);
                            })
                        }
                    >
                        Upload paper
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                    <label htmlFor="paper-file" className="text-sm font-medium text-secondary">
                        Paper file (PDF, HTML or text, up to 50 MB)
                    </label>
                    <input
                        id="paper-file"
                        type="file"
                        accept=".pdf,.txt,.html,application/pdf,text/plain,text/html"
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                        className="rounded-lg text-sm text-secondary ring-1 ring-primary file:mr-3 file:rounded-l-lg file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium focus-visible:outline-2 focus-visible:outline-focus-ring"
                    />
                </div>
                <Input label="DOI" value={doi} onChange={setDoi} hint="Used for the deterministic identity check." />
                <Input label="Title" value={title} onChange={setTitle} />
                <TextArea label="Rights statement" hint="At least 10 characters, e.g. “Author-provided copy licensed for this study.”" isRequired value={rights} onChange={setRights} rows={2} />
                <Checkbox isSelected={attest} onChange={setAttest} label="I have the right to use this file for this project" />
                <ErrorAlert error={s.error} />
            </div>
        </DialogShell>
    );
}

function ScreenDialog({ projectId, paper, onClose, onDone }: { projectId: string; paper: PaperEntry; onClose: () => void; onDone: () => void }) {
    const [stage, setStage] = useState("title_abstract");
    const [decision, setDecision] = useState("include");
    const [reason, setReason] = useState("");
    const s = useSubmit(onDone, onClose);
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Screening decision"
            description={paper.title}
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button isLoading={s.busy} isDisabled={reason.trim().length < 3} onClick={() => s.run(() => api.post(`/v1/projects/${projectId}/papers/${paper.id}/screen`, { stage, decision, reason, criteria: [] }))}>
                        Record decision
                    </Button>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <NativeSelect label="Stage" value={stage} onChange={(e) => setStage(e.target.value)} options={[{ label: "Title and abstract", value: "title_abstract" }, { label: "Full text", value: "full_text" }]} />
                <NativeSelect label="Decision" value={decision} onChange={(e) => setDecision(e.target.value)} options={[{ label: "Include", value: "include" }, { label: "Exclude", value: "exclude" }, { label: "Maybe", value: "maybe" }]} />
                <TextArea label="Reason" isRequired value={reason} onChange={setReason} rows={2} />
                <ErrorAlert error={s.error} />
            </div>
        </DialogShell>
    );
}

function NotesDialog({ projectId, paper, onClose, onDone }: { projectId: string; paper: PaperEntry; onClose: () => void; onDone: () => void }) {
    const [notes, setNotes] = useState(paper.notes ?? "");
    const s = useSubmit(onDone, onClose);
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Private notes"
            description="Notes stay private to this project and are never shared with other workspaces."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button isLoading={s.busy} onClick={() => s.run(() => api.patch(`/v1/projects/${projectId}/papers/${paper.id}`, { notes }))}>
                        Save notes
                    </Button>
                </>
            }
        >
            <TextArea label="Notes" value={notes} onChange={setNotes} rows={5} />
            <ErrorAlert error={s.error} />
        </DialogShell>
    );
}

function PassageDialog({ projectId, paper, onClose, onDone }: { projectId: string; paper: PaperEntry; onClose: () => void; onDone: () => void }) {
    const [quote, setQuote] = useState("");
    const [role, setRole] = useState("claim");
    const [page, setPage] = useState("");
    const [section, setSection] = useState("");
    const [result, setResult] = useState<PassageEntry | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    return (
        <DialogShell
            isOpen
            onOpenChange={(o) => !o && onClose()}
            title="Add a passage"
            description="Copy the passage verbatim. It is checked against stored full text or the abstract when available; otherwise it is recorded as your quote and machine checks cannot confirm it."
            footer={
                result ? (
                    <Button
                        onClick={() => {
                            onDone();
                            onClose();
                        }}
                    >
                        Done
                    </Button>
                ) : (
                    <>
                        <Button color="secondary" onClick={onClose}>
                            Cancel
                        </Button>
                        <Button
                            isLoading={busy}
                            isDisabled={quote.trim().length < 8}
                            onClick={async () => {
                                setBusy(true);
                                setError(undefined);
                                try {
                                    setResult(
                                        await api.post<PassageEntry>(`/v1/projects/${projectId}/papers/${paper.id}/passages`, {
                                            quote,
                                            role,
                                            page: page ? Number(page) : null,
                                            section: section || null,
                                        }),
                                    );
                                } catch (err) {
                                    setError(err);
                                } finally {
                                    setBusy(false);
                                }
                            }}
                        >
                            Add passage
                        </Button>
                    </>
                )
            }
        >
            {result ? (
                <p role="status" className={result.verified_in_source ? "text-sm text-success-primary" : "text-sm text-warning-primary"}>
                    {result.verified_in_source
                        ? `Found verbatim in the ${result.source_kind === "fulltext" ? "stored full text" : "abstract"}.`
                        : "Not found in any stored text: recorded as your quote; machine checks cannot confirm it."}
                </p>
            ) : (
                <div className="flex flex-col gap-3">
                    <TextArea label="Verbatim passage" isRequired value={quote} onChange={setQuote} rows={4} />
                    <NativeSelect
                        label="Role"
                        value={role}
                        onChange={(e) => setRole(e.target.value)}
                        options={["claim", "method", "result", "limitation", "population", "dataset", "definition", "table"].map((r) => ({ label: r, value: r }))}
                    />
                    <div className="grid gap-3 sm:grid-cols-2">
                        <Input label="Page" inputMode="numeric" value={page} onChange={setPage} />
                        <Input label="Section" value={section} onChange={setSection} />
                    </div>
                    <ErrorAlert error={error} />
                </div>
            )}
        </DialogShell>
    );
}
