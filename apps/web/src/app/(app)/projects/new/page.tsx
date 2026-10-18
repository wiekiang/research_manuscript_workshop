"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { TextArea } from "@/components/base/textarea/textarea";
import { ErrorAlert } from "@/components/research/error-alert";
import { PageHeader } from "@/components/research/page-header";
import { api, newIdempotencyKey } from "@/lib/api/client";
import type { Project } from "@/lib/api/types";
import { COPY } from "@/lib/copy";

export default function NewProjectPage() {
    const router = useRouter();
    const [title, setTitle] = useState("");
    const [topic, setTopic] = useState("");
    const [description, setDescription] = useState("");
    const [budget, setBudget] = useState("50");
    const [ack, setAck] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    // One key per form instance so a double submit or retried request creates exactly one project.
    const idemKey = useMemo(() => newIdempotencyKey("project"), []);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        setError(undefined);
        try {
            const cents = budget.trim() ? Math.round(Number(budget) * 100) : undefined;
            const p = await api.post<Project>(
                "/v1/projects",
                { title, topic: topic || null, description: description || null, budget_cap_cents: Number.isFinite(cents) ? cents : undefined, responsibility_acknowledged: ack },
                idemKey,
            );
            router.push(`/projects/${p.id}/cfp`);
        } catch (err) {
            setError(err);
            setBusy(false);
        }
    };

    return (
        <div className="flex max-w-3xl flex-col gap-8">
            <PageHeader title="New research project" description="Name the work and set a cost ceiling. You will import the official call for papers next." />
            <form onSubmit={submit} className="flex flex-col gap-6" noValidate>
                <Input label="Project title" isRequired value={title} onChange={setTitle} hint="At least 3 characters." />
                <Input label="Topic" value={topic} onChange={setTopic} hint="Field, research area or problem, in a few words." />
                <TextArea label="Description" value={description} onChange={setDescription} rows={3} />
                <Input
                    label="Cost cap (USD)"
                    type="number"
                    inputMode="decimal"
                    value={budget}
                    onChange={setBudget}
                    hint="Paid AI, search and compute work stops at this ceiling. Only a project owner can raise it, with a recorded reason."
                />
                <section aria-labelledby="responsibility-title" className="flex flex-col gap-3 rounded-2xl border-2 border-utility-amber-300 p-5">
                    <h2 id="responsibility-title" className="font-display text-lg font-semibold text-primary">
                        Your responsibility
                    </h2>
                    <p data-testid="responsibility-message" className="text-md text-primary">
                        {COPY.responsibility_message}
                    </p>
                    <Checkbox isSelected={ack} onChange={setAck} label="I have read this and accept responsibility for my contribution" />
                </section>
                <ErrorAlert error={error} />
                <div className="flex gap-3">
                    <Button type="submit" size="lg" isDisabled={!ack || title.trim().length < 3} isLoading={busy}>
                        Create project
                    </Button>
                    <Button color="secondary" size="lg" href="/dashboard">
                        Cancel
                    </Button>
                </div>
            </form>
        </div>
    );
}
