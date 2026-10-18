"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { Section } from "@/components/research/page-header";
import { api } from "@/lib/api/client";
import type { ContributionEntry } from "@/lib/api/types";
import { formatDateTime, humanize } from "@/lib/format";

const TYPES = ["dataset", "code", "results", "notes", "annotations", "observations", "theoretical_argument", "interview_protocol", "interpretation", "limitations", "methodological_decision", "other"];
const PII = ["none", "pseudonymized", "personal", "sensitive"];

/** Researcher-supplied files and notes. Files need a rights statement and pass type, size and malware checks. */
export function ContributionsPanel({ projectId, items, canEdit, onChanged }: { projectId: string; items: ContributionEntry[]; canEdit: boolean; onChanged: () => void }) {
    const [open, setOpen] = useState(false);
    const [file, setFile] = useState<File | null>(null);
    const [type, setType] = useState("dataset");
    const [title, setTitle] = useState("");
    const [text, setText] = useState("");
    const [pii, setPii] = useState("none");
    const [rights, setRights] = useState("");
    const [license, setLicense] = useState("");
    const [visibility, setVisibility] = useState("private");
    const [relation, setRelation] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const fd = new FormData();
            if (file) fd.append("file", file);
            fd.append("contribution_type", type);
            fd.append("title", title);
            if (text.trim()) fd.append("text", text);
            fd.append("pii_classification", pii);
            if (rights.trim()) fd.append("rights_statement", rights);
            if (license.trim()) fd.append("license", license);
            fd.append("visibility", visibility);
            if (relation.trim()) fd.append("relation_to_protocol", relation);
            await api.post(`/v1/projects/${projectId}/contributions`, fd);
            setOpen(false);
            setFile(null);
            setTitle("");
            setText("");
            setRights("");
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <Section
            title="Your contributions"
            description="Data, code, notes and arguments you supply. Each is stored as an immutable artifact and recorded in the contribution ledger."
            actions={
                canEdit && (
                    <Button size="sm" color="secondary" onClick={() => setOpen(true)}>
                        Add a contribution
                    </Button>
                )
            }
        >
            {items.length === 0 && <p className="text-sm text-tertiary">No contributions yet.</p>}
            <ul className="flex flex-col gap-2">
                {items.map((c) => (
                    <li key={c.id} data-testid="contribution-row" className="flex flex-col gap-1 rounded-xl bg-primary p-3 ring-1 ring-secondary">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-medium text-primary">{c.title}</span>
                            <span className="text-xs text-tertiary">
                                {humanize(c.type)} · PII: {c.pii_classification} · {c.visibility} · {formatDateTime(c.created_at)}
                            </span>
                        </div>
                        {c.rights_statement && <p className="text-xs text-tertiary">Rights: {c.rights_statement}</p>}
                        {c.text && <p className="line-clamp-3 text-sm text-secondary">{c.text}</p>}
                        <p className="text-xs text-tertiary">{c.artifact_id ? `File artifact ${c.artifact_id.slice(0, 8)} · sha256 ${c.content_hash.slice(0, 12)}` : "Text contribution"}</p>
                    </li>
                ))}
            </ul>
            <DialogShell
                isOpen={open}
                onOpenChange={setOpen}
                title="Add a contribution"
                description="Attach a file or write the contribution. Personal or sensitive data is stored as restricted and never sent to a model."
                size="lg"
                footer={
                    <>
                        <Button color="secondary" onClick={() => setOpen(false)}>
                            Cancel
                        </Button>
                        <Button isLoading={busy} isDisabled={title.trim().length < 3 || (!file && !text.trim())} onClick={submit}>
                            Save contribution
                        </Button>
                    </>
                }
            >
                <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="contribution-file" className="text-sm font-medium text-secondary">
                            File (optional; up to 200 MB)
                        </label>
                        <input
                            id="contribution-file"
                            type="file"
                            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                            className="rounded-lg text-sm text-secondary ring-1 ring-primary file:mr-3 file:rounded-l-lg file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium focus-visible:outline-2 focus-visible:outline-focus-ring"
                        />
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <NativeSelect label="Type" value={type} onChange={(e) => setType(e.target.value)} options={TYPES.map((t) => ({ label: humanize(t), value: t }))} />
                        <NativeSelect label="Personal data classification" value={pii} onChange={(e) => setPii(e.target.value)} options={PII.map((t) => ({ label: humanize(t), value: t }))} />
                    </div>
                    <Input label="Title" isRequired value={title} onChange={setTitle} />
                    <TextArea label="Text (optional when a file is attached)" value={text} onChange={setText} rows={3} />
                    <TextArea label="Rights statement" hint="Required for files: origin, licence and consent." value={rights} onChange={setRights} rows={2} />
                    <div className="grid gap-3 sm:grid-cols-2">
                        <Input label="Licence" value={license} onChange={setLicense} />
                        <NativeSelect
                            label="Visibility"
                            value={visibility}
                            onChange={(e) => setVisibility(e.target.value)}
                            options={["private", "restricted", "public"].map((v) => ({ label: humanize(v), value: v }))}
                        />
                    </div>
                    <TextArea label="Relation to the protocol" value={relation} onChange={setRelation} rows={2} />
                    <ErrorAlert error={error} />
                </div>
            </DialogShell>
        </Section>
    );
}
