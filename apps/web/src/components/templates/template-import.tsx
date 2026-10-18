"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import { cx } from "@/utils/cx";

const MODES = [
    { label: "Initial submission", value: "submission" },
    { label: "Camera-ready", value: "camera_ready" },
];

export function TemplateImport({ projectId, onQueued }: { projectId: string; onQueued: () => void }) {
    const [tab, setTab] = useState<"url" | "file">("url");
    return (
        <section aria-labelledby="tpl-import-title" className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <div>
                <h2 id="tpl-import-title" className="font-display text-lg font-semibold text-primary">
                    Add the official LaTeX template
                </h2>
                <p className="text-sm text-tertiary">
                    Use the template linked from the conference, organizer or publisher. The archive is checked for path traversal, links, nested archives and executables, and is
                    never edited: your content is inserted through a versioned adapter and compiled in a no-network sandbox with shell escape disabled.
                </p>
            </div>
            <div role="tablist" aria-label="Template source" className="flex gap-1 rounded-lg bg-secondary p-1">
                {(["url", "file"] as const).map((t) => (
                    <button
                        key={t}
                        role="tab"
                        type="button"
                        aria-selected={tab === t}
                        aria-controls={`tpl-${t}`}
                        onClick={() => setTab(t)}
                        className={cx(
                            "flex-1 rounded-md px-3 py-1.5 text-sm font-medium outline-focus-ring focus-visible:outline-2",
                            tab === t ? "bg-primary text-primary shadow-xs" : "text-tertiary hover:text-secondary",
                        )}
                    >
                        {t === "url" ? "Import from the official link" : "Upload the official ZIP"}
                    </button>
                ))}
            </div>
            {tab === "url" ? <UrlForm projectId={projectId} onQueued={onQueued} /> : <UploadForm projectId={projectId} onQueued={onQueued} />}
        </section>
    );
}

function UrlForm({ projectId, onQueued }: { projectId: string; onQueued: () => void }) {
    const [url, setUrl] = useState("");
    const [mode, setMode] = useState("submission");
    const [license, setLicense] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [done, setDone] = useState(false);
    return (
        <form
            id="tpl-url"
            role="tabpanel"
            className="flex flex-col gap-3"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                try {
                    await api.post(`/v1/projects/${projectId}/templates/import`, { url, mode, license_note: license || null });
                    setDone(true);
                    onQueued();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <Input label="Official template URL (ZIP)" type="url" isRequired value={url} onChange={(v) => { setUrl(v); setDone(false); }} />
            <NativeSelect label="Template mode" value={mode} onChange={(e) => setMode(e.target.value)} options={MODES} />
            <Input label="License or reuse note (as stated by the source)" value={license} onChange={setLicense} />
            <ErrorAlert error={error} />
            {done && <p className="text-sm text-success-primary">Retrieval queued. Progress appears below.</p>}
            <div>
                <Button type="submit" isLoading={busy} isDisabled={!url}>
                    Import template
                </Button>
            </div>
        </form>
    );
}

function UploadForm({ projectId, onQueued }: { projectId: string; onQueued: () => void }) {
    const [file, setFile] = useState<File | null>(null);
    const [origin, setOrigin] = useState("");
    const [statement, setStatement] = useState("");
    const [mode, setMode] = useState("submission");
    const [license, setLicense] = useState("");
    const [attest, setAttest] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [done, setDone] = useState(false);
    return (
        <form
            id="tpl-file"
            role="tabpanel"
            className="flex flex-col gap-3"
            onSubmit={async (e) => {
                e.preventDefault();
                if (!file) return;
                setBusy(true);
                setError(undefined);
                try {
                    const fd = new FormData();
                    fd.append("file", file);
                    fd.append("declared_origin_url", origin);
                    fd.append("origin_statement", statement);
                    fd.append("mode", mode);
                    if (license) fd.append("license_note", license);
                    fd.append("attest_official", attest ? "true" : "false");
                    await api.post(`/v1/projects/${projectId}/templates/upload`, fd);
                    setDone(true);
                    onQueued();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <p className="text-sm text-tertiary">Use this when the official link cannot be fetched automatically. The declared origin is recorded with the archive.</p>
            <div className="flex flex-col gap-1.5">
                <label htmlFor="tpl-zip" className="text-sm font-medium text-secondary">
                    Template archive (ZIP, up to 50 MB)
                </label>
                <input
                    id="tpl-zip"
                    name="file"
                    type="file"
                    accept=".zip,application/zip"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="rounded-lg text-sm text-secondary ring-1 ring-primary file:mr-3 file:rounded-l-lg file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium focus-visible:outline-2 focus-visible:outline-focus-ring"
                />
            </div>
            <Input label="Official origin URL" type="url" isRequired value={origin} onChange={setOrigin} />
            <TextArea label="How you obtained it" hint="At least 10 characters, e.g. “Downloaded from the publisher's author kit page.”" isRequired value={statement} onChange={setStatement} rows={2} />
            <NativeSelect label="Template mode" value={mode} onChange={(e) => setMode(e.target.value)} options={MODES} />
            <Input label="License or reuse note (as stated by the source)" value={license} onChange={setLicense} />
            <Checkbox isSelected={attest} onChange={setAttest} label="This is the official template from the conference, organizer or publisher" />
            <ErrorAlert error={error} />
            {done && <p className="text-sm text-success-primary">Template stored. Analysis and sample compiles are running; progress appears below.</p>}
            <div>
                <Button type="submit" isLoading={busy} isDisabled={!file || !attest || !origin || statement.trim().length < 10}>
                    Upload and analyse
                </Button>
            </div>
        </form>
    );
}
