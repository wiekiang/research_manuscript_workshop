"use client";

import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash01 } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { ApiError, api } from "@/lib/api/client";
import type { AuthorInput, AuthorsView, Member } from "@/lib/api/types";
import { CREDIT_LABEL, CREDIT_ROLES, authorToInput, emptyAuthor, moveItem, serverProblems } from "@/lib/submission";

/** Problems the server returned for the last save, shown verbatim (e.g. "AI tools cannot be listed as authors"). */
export function AuthorProblems({ problems }: { problems: string[] }) {
    if (problems.length === 0) return null;
    return (
        <div role="alert" data-testid="author-problems" className="rounded-xl border border-error_subtle bg-error-primary p-4">
            <p className="text-sm font-semibold text-error-primary">The author record was not saved</p>
            <ul className="mt-1 list-disc pl-5 text-sm text-secondary">
                {problems.map((p) => (
                    <li key={p}>{p}</li>
                ))}
            </ul>
        </div>
    );
}

function AuthorFields({ a, index, count, members, onChange, onMove, onRemove, onCorresponding }: {
    a: AuthorInput;
    index: number;
    count: number;
    members: Member[];
    onChange: (patch: Partial<AuthorInput>) => void;
    onMove: (to: number) => void;
    onRemove: () => void;
    onCorresponding: () => void;
}) {
    const n = index + 1;
    return (
        <fieldset data-testid="author-form" className="flex flex-col gap-3 rounded-xl border border-secondary p-4">
            <legend className="px-1 text-sm font-semibold text-primary">Author {n}</legend>
            <div className="flex flex-wrap gap-2">
                <Button size="sm" color="secondary" iconLeading={ArrowUp} isDisabled={index === 0} onClick={() => onMove(index - 1)} aria-label={`Move author ${n} up`}>
                    Up
                </Button>
                <Button size="sm" color="secondary" iconLeading={ArrowDown} isDisabled={index === count - 1} onClick={() => onMove(index + 1)} aria-label={`Move author ${n} down`}>
                    Down
                </Button>
                <Button size="sm" color="secondary-destructive" iconLeading={Trash01} onClick={onRemove} aria-label={`Remove author ${n}`}>
                    Remove
                </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
                <Input label={`Full name (author ${n})`} isRequired value={a.name} onChange={(v) => onChange({ name: v })} />
                <Input label={`Email (author ${n})`} value={a.email ?? ""} onChange={(v) => onChange({ email: v || null })} />
                <Input
                    label={`Affiliations (author ${n})`}
                    hint="Separate several affiliations with a semicolon."
                    value={a.affiliations.join("; ")}
                    onChange={(v) => onChange({ affiliations: v.split(";").map((x) => x.trim()).filter(Boolean) })}
                />
                <Input label={`ORCID (author ${n})`} hint="Format 0000-0000-0000-0000" value={a.orcid ?? ""} onChange={(v) => onChange({ orcid: v || null })} />
                <NativeSelect
                    label={`Linked project member (author ${n})`}
                    value={a.user_id ?? ""}
                    onChange={(e) => onChange({ user_id: e.target.value || null })}
                    options={[{ value: "", label: "Not a project member (offline attestation needed)" }, ...members.map((m) => ({ value: m.user_id, label: `${m.display_name} (${m.email})` }))]}
                />
                <div className="flex items-end">
                    <Checkbox isSelected={a.corresponding} onChange={(v) => v && onCorresponding()} label="Corresponding author (signs H4)" />
                </div>
            </div>
            <fieldset className="flex flex-col gap-2">
                <legend className="text-sm font-medium text-secondary">Contribution roles (CRediT)</legend>
                <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                    {CREDIT_ROLES.map((r) => (
                        <Checkbox
                            key={r}
                            isSelected={a.contribution_roles.includes(r)}
                            onChange={(v) => onChange({ contribution_roles: v ? [...a.contribution_roles, r] : a.contribution_roles.filter((x) => x !== r) })}
                            label={CREDIT_LABEL[r]}
                        />
                    ))}
                </div>
            </fieldset>
            <TextArea label={`Contribution statement (author ${n})`} isRequired value={a.contribution_statement} onChange={(v) => onChange({ contribution_statement: v })} rows={2} />
            <div className="grid gap-3 sm:grid-cols-2">
                <TextArea label={`Competing interests (author ${n})`} hint="Write “None declared” if there are none." isRequired value={a.competing_interests} onChange={(v) => onChange({ competing_interests: v })} rows={2} />
                <TextArea label={`Funding (author ${n})`} hint="Write “No external funding” if there is none." isRequired value={a.funding} onChange={(v) => onChange({ funding: v })} rows={2} />
            </div>
            <Checkbox
                isSelected={a.human_confirmed}
                onChange={(v) => onChange({ human_confirmed: v })}
                label="This entry describes a natural person. AI tools cannot be authors; describe AI use in the disclosures instead."
            />
        </fieldset>
    );
}

/**
 * Ordered author record. Saving replaces the whole record against `expected_record_version`; a changed record
 * invalidates H4 and packages that bound the previous version. Only the project owner can save. Mount it with
 * `key={record_version}` so a newly saved record resets the form without discarding edits on a mere re-fetch.
 */
export function AuthorsEditor({ view, members, projectId, canSave, onSaved }: { view: AuthorsView; members: Member[]; projectId: string; canSave: boolean; onSaved: () => void }) {
    const [authors, setAuthors] = useState<AuthorInput[]>(() => (view.authors.length ? view.authors.map(authorToInput) : [emptyAuthor(true)]));
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [problems, setProblems] = useState<string[]>([]);

    const patch = (i: number, p: Partial<AuthorInput>) => setAuthors((xs) => xs.map((x, j) => (j === i ? { ...x, ...p } : x)));

    const save = async () => {
        setBusy(true);
        setError(undefined);
        setProblems([]);
        try {
            await api.put(`/v1/projects/${projectId}/authors`, { expected_record_version: view.record_version, authors });
            onSaved();
        } catch (err) {
            const p = err instanceof ApiError ? serverProblems(err.details) : [];
            if (p.length) setProblems(p);
            else setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-4">
            {authors.map((a, i) => (
                <AuthorFields
                    key={i}
                    a={a}
                    index={i}
                    count={authors.length}
                    members={members}
                    onChange={(p) => patch(i, p)}
                    onMove={(to) => setAuthors((xs) => moveItem(xs, i, to))}
                    onRemove={() => setAuthors((xs) => xs.filter((_, j) => j !== i))}
                    onCorresponding={() => setAuthors((xs) => xs.map((x, j) => ({ ...x, corresponding: j === i })))}
                />
            ))}
            <div className="flex flex-wrap gap-2">
                <Button size="sm" color="secondary" iconLeading={Plus} onClick={() => setAuthors((xs) => [...xs, emptyAuthor(false)])}>
                    Add author
                </Button>
                {canSave && (
                    <Button size="sm" isLoading={busy} onClick={save}>
                        Save author record
                    </Button>
                )}
            </div>
            {!canSave && <p className="text-sm text-tertiary">Only the project owner can change the author record.</p>}
            <AuthorProblems problems={problems} />
            <ErrorAlert error={error} />
        </div>
    );
}
