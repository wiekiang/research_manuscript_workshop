"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { api, newIdempotencyKey } from "@/lib/api/client";
import { cx } from "@/utils/cx";

export function ImportPanel({ projectId, onQueued }: { projectId: string; onQueued: () => void }) {
    const [tab, setTab] = useState<"url" | "file">("url");
    return (
        <section aria-labelledby="import-title" className="flex flex-col gap-4 rounded-2xl bg-primary p-5 ring-1 ring-secondary">
            <div>
                <h2 id="import-title" className="font-display text-lg font-semibold text-primary">
                    Add the official call for papers
                </h2>
                <p className="text-sm text-tertiary">
                    Use the organizer&apos;s own CFP page, not a third-party listing. The page is fetched by an isolated service, scanned, and stored as an immutable snapshot before any agent reads it.
                </p>
            </div>
            <div role="tablist" aria-label="Import method" className="flex gap-1 rounded-lg bg-secondary p-1">
                {(["url", "file"] as const).map((t) => (
                    <button
                        key={t}
                        role="tab"
                        type="button"
                        aria-selected={tab === t}
                        aria-controls={`import-${t}`}
                        onClick={() => setTab(t)}
                        className={cx(
                            "flex-1 rounded-md px-3 py-1.5 text-sm font-medium outline-focus-ring focus-visible:outline-2",
                            tab === t ? "bg-primary text-primary shadow-xs" : "text-tertiary hover:text-secondary",
                        )}
                    >
                        {t === "url" ? "Import from the official URL" : "Supply the official document"}
                    </button>
                ))}
            </div>
            {tab === "url" ? <UrlForm projectId={projectId} onQueued={onQueued} /> : <FileForm projectId={projectId} onQueued={onQueued} />}
        </section>
    );
}

function UrlForm({ projectId, onQueued }: { projectId: string; onQueued: () => void }) {
    const [url, setUrl] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [done, setDone] = useState(false);
    const key = useMemo(() => newIdempotencyKey("cfp-import"), []);
    return (
        <form
            id="import-url"
            role="tabpanel"
            className="flex flex-col gap-3"
            onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setError(undefined);
                try {
                    await api.post("/v1/conferences/import", { project_id: projectId, url }, `${key}:${url}`);
                    setDone(true);
                    onQueued();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <Input label="Official CFP URL" type="url" placeholder="https://conference.org/2027/call-for-papers" isRequired value={url} onChange={(v) => { setUrl(v); setDone(false); }} />
            <ErrorAlert error={error} />
            {done && <p className="text-sm text-success-primary">Import queued. Progress appears below.</p>}
            <div>
                <Button type="submit" isLoading={busy} isDisabled={!url}>
                    Import CFP
                </Button>
            </div>
        </form>
    );
}

function FileForm({ projectId, onQueued }: { projectId: string; onQueued: () => void }) {
    const [file, setFile] = useState<File | null>(null);
    const [origin, setOrigin] = useState("");
    const [statement, setStatement] = useState("");
    const [attest, setAttest] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [done, setDone] = useState(false);
    return (
        <form
            id="import-file"
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
                    fd.append("attest_official", attest ? "true" : "false");
                    await api.post(`/v1/projects/${projectId}/cfp/documents`, fd);
                    setDone(true);
                    onQueued();
                } catch (err) {
                    setError(err);
                } finally {
                    setBusy(false);
                }
            }}
        >
            <p className="text-sm text-tertiary">Use this when the page cannot be fetched (for example behind a login). The document is scanned and its declared origin is recorded with it.</p>
            <div className="flex flex-col gap-1.5">
                <label htmlFor="cfp-file" className="text-sm font-medium text-secondary">
                    Document (HTML, PDF or plain text, up to 25 MB)
                </label>
                <input
                    id="cfp-file"
                    name="file"
                    type="file"
                    accept=".html,.htm,.pdf,.txt,text/html,application/pdf,text/plain"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="rounded-lg text-sm text-secondary ring-1 ring-primary file:mr-3 file:rounded-l-lg file:border-0 file:bg-secondary file:px-3 file:py-2 file:text-sm file:font-medium focus-visible:outline-2 focus-visible:outline-focus-ring"
                />
            </div>
            <Input label="Where it came from (official URL)" type="url" isRequired value={origin} onChange={setOrigin} />
            <TextArea label="How you obtained it" hint="At least 10 characters, e.g. “Saved from the organizer's CFP page on 18 Oct 2026.”" isRequired value={statement} onChange={setStatement} rows={2} />
            <Checkbox isSelected={attest} onChange={setAttest} label="This is the official CFP or policy text from the organizer or publisher" />
            <ErrorAlert error={error} />
            {done && <p className="text-sm text-success-primary">Document stored. Extraction is running; progress appears below.</p>}
            <div>
                <Button type="submit" isLoading={busy} isDisabled={!file || !attest || !origin || statement.trim().length < 10}>
                    Upload and extract
                </Button>
            </div>
        </form>
    );
}
