"use client";

import { Button } from "@/components/base/buttons/button";
import { StatusBadge } from "@/components/research/status-badge";
import type { CfpRule, Deadline } from "@/lib/api/types";
import { formatInStatedZone, formatUtc, humanize } from "@/lib/format";

interface Props {
    deadlines: Deadline[];
    rules: CfpRule[];
    canResolve: boolean;
    onResolve: (rule: CfpRule) => void;
}

export function DeadlinesTable({ deadlines, rules, canResolve, onResolve }: Props) {
    if (deadlines.length === 0) return <p className="text-sm text-tertiary">No deadlines extracted yet.</p>;
    const ruleById = new Map(rules.map((r) => [r.id, r]));
    return (
        <div className="overflow-x-auto rounded-2xl bg-primary ring-1 ring-secondary">
            <table className="w-full min-w-[760px] text-left text-sm">
                <caption className="sr-only">Deadlines with the timezone stated by the official source</caption>
                <thead className="bg-secondary text-xs text-tertiary">
                    <tr>
                        <th scope="col" className="px-4 py-2 font-medium">Deadline</th>
                        <th scope="col" className="px-4 py-2 font-medium">As stated</th>
                        <th scope="col" className="px-4 py-2 font-medium">In UTC</th>
                        <th scope="col" className="px-4 py-2 font-medium">Governs</th>
                        <th scope="col" className="px-4 py-2 font-medium">Status</th>
                        {canResolve && <th scope="col" className="px-4 py-2 font-medium"><span className="sr-only">Action</span></th>}
                    </tr>
                </thead>
                <tbody className="divide-y divide-secondary">
                    {deadlines.map((d) => {
                        const rule = ruleById.get(d.rule_id);
                        const stated = formatInStatedZone(d.due_at, d.stated_timezone);
                        return (
                            <tr key={d.id} data-testid={`deadline-${d.deadline_kind}`} data-status={d.status}>
                                <th scope="row" className="px-4 py-3 font-medium text-primary">
                                    {humanize(d.deadline_kind)}
                                    {d.mandatory && <span className="block text-xs font-normal text-tertiary">Mandatory</span>}
                                    {d.track && <span className="block text-xs font-normal text-tertiary">{d.track}</span>}
                                </th>
                                <td className="px-4 py-3 text-secondary">
                                    {d.stated_date ?? "—"} {d.stated_time ?? ""}{" "}
                                    <span className={d.stated_timezone ? "" : "text-error-primary"}>{d.stated_timezone ?? "no timezone stated"}</span>
                                    {stated && <span className="block text-xs text-tertiary">{stated}</span>}
                                </td>
                                <td className="px-4 py-3 text-secondary">{d.due_at ? formatUtc(d.due_at) : <span className="text-error-primary">Unresolved</span>}</td>
                                <td className="px-4 py-3 text-tertiary">{d.governs_actions.length ? d.governs_actions.map(humanize).join(", ") : "Context only"}</td>
                                <td className="px-4 py-3">
                                    <StatusBadge status={d.applicability === "not_applicable" ? "rejected" : d.status} label={d.applicability === "not_applicable" ? "Not applicable" : undefined} />
                                </td>
                                {canResolve && (
                                    <td className="px-4 py-3">
                                        {rule && (
                                            <Button size="sm" color={d.status === "needs_human_resolution" ? "primary" : "secondary"} onClick={() => onResolve(rule)} aria-label={`Resolve ${humanize(d.deadline_kind)} deadline`}>
                                                {d.status === "needs_human_resolution" ? "Resolve" : "Change"}
                                            </Button>
                                        )}
                                    </td>
                                )}
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
