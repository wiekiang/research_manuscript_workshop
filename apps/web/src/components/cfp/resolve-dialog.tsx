"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { SourceQuote } from "@/components/research/provenance-link";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { CfpRule } from "@/lib/api/types";
import { humanize } from "@/lib/format";

interface Props {
    projectId: string;
    rule: CfpRule | null;
    onClose: () => void;
    onResolved: () => void;
}

export function ResolveDialog({ projectId, rule, onClose, onResolved }: Props) {
    const [action, setAction] = useState("confirm");
    const [rationale, setRationale] = useState("");
    const [valueText, setValueText] = useState("");
    const [date, setDate] = useState("");
    const [time, setTime] = useState("");
    const [timezone, setTimezone] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();

    useEffect(() => {
        setAction("confirm");
        setRationale("");
        setValueText("");
        setDate(rule?.item_type === "deadline" ? (rule.value ?? "") : "");
        setTime("");
        setTimezone("");
        setError(undefined);
    }, [rule]);

    if (!rule) return null;
    const isDeadline = rule.item_type === "deadline";

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            const body: Record<string, unknown> = { rule_id: rule.id, action, rationale };
            if (action === "edit" && valueText) body.value_text = valueText;
            if (isDeadline && action !== "reject" && action !== "not_applicable") {
                if (date && date !== rule.value) body.date = date;
                if (time) body.time = time;
                if (timezone) body.timezone = timezone;
            }
            await api.post(`/v1/projects/${projectId}/cfp/resolve`, body);
            onResolved();
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <DialogShell
            isOpen={!!rule}
            onOpenChange={(o) => !o && onClose()}
            size="lg"
            title={`Resolve: ${humanize(rule.rule_key)}${rule.track ? ` (${rule.track})` : ""}`}
            description="Check the source sentence yourself. Your decision and rationale are recorded with the rule; extracted values are kept for audit."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button isLoading={busy} isDisabled={rationale.trim().length < 5} onClick={submit}>
                        Record resolution
                    </Button>
                </>
            }
        >
            <SourceQuote quote={rule.quote} locator={rule.locator} />
            {rule.problems.length > 0 && (
                <ul className="list-disc rounded-xl bg-warning-primary py-2 pr-3 pl-8 text-sm text-utility-amber-700">
                    {rule.problems.map((p) => (
                        <li key={p}>{p}</li>
                    ))}
                </ul>
            )}
            {rule.observations.length > 1 && (
                <div className="text-sm text-secondary">
                    <p className="font-medium">What each method found</p>
                    <ul className="mt-1 list-disc pl-5">
                        {rule.observations.map((o, i) => (
                            <li key={`${o.method}-${i}`}>
                                {humanize(o.method)}: {isDeadline ? `${o.date ?? "?"} ${o.time ?? ""} ${o.timezone ?? "(no timezone)"}` : (o.value ?? o.value_text ?? "—")}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            <NativeSelect
                label="Decision"
                value={action}
                onChange={(e) => setAction(e.target.value)}
                options={[
                    { label: "Confirm: the source says this", value: "confirm" },
                    { label: "Edit: the source says something different", value: "edit" },
                    { label: "Reject: the source does not say this", value: "reject" },
                    { label: "Not applicable to my submission", value: "not_applicable" },
                ]}
            />
            {action === "edit" && !isDeadline && <TextArea label="What the rule actually says" value={valueText} onChange={setValueText} rows={2} />}
            {isDeadline && action !== "reject" && action !== "not_applicable" && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <Input label="Date (YYYY-MM-DD)" value={date} onChange={setDate} placeholder="2027-01-21" />
                    <Input label="Time (24h)" value={time} onChange={setTime} placeholder="23:59" />
                    <Input label="Timezone" value={timezone} onChange={setTimezone} placeholder="AoE, UTC-12, PDT…" hint="As the official source states it." />
                </div>
            )}
            <TextArea label="Rationale" isRequired value={rationale} onChange={setRationale} rows={3} hint="Why this is correct, e.g. which sentence or which organizer statement you relied on." />
            <ErrorAlert error={error} />
        </DialogShell>
    );
}
