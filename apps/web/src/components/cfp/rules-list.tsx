"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Toggle } from "@/components/base/toggle/toggle";
import { SourceQuote } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { VerificationMethodLabel } from "@/components/research/verification-method-label";
import type { CfpRule } from "@/lib/api/types";
import { humanize } from "@/lib/format";

const AGREEMENT: Record<string, string> = {
    agreed: "Independent methods agree",
    conflict: "Methods disagree",
    single_pass: "Found by one method",
};

interface Props {
    rules: CfpRule[];
    canResolve: boolean;
    onResolve: (rule: CfpRule) => void;
}

/** The model provider recorded on the rule's own model-assisted observation (or its independent check). */
export function ruleModelProvider(r: CfpRule): string | null {
    const obs = r.observations.find((o) => o.method === "model_assisted" && o.provider);
    if (obs?.provider) return obs.provider;
    const sp = r.second_pass?.provider;
    return typeof sp === "string" ? sp : null;
}

export function RulesList({ rules, canResolve, onResolve }: Props) {
    const [onlyOpen, setOnlyOpen] = useState(false);
    const shown = rules.filter((r) => r.item_type === "rule" && (!onlyOpen || r.status === "needs_human_resolution"));
    const grouped = useMemo(() => {
        const g = new Map<string, CfpRule[]>();
        for (const r of shown) g.set(r.category, [...(g.get(r.category) ?? []), r]);
        const byKey = (a: CfpRule, b: CfpRule) => a.rule_key.localeCompare(b.rule_key) || (a.track ?? "").localeCompare(b.track ?? "");
        return [...g.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([c, items]) => [c, items.slice().sort(byKey)] as const);
    }, [shown]);

    return (
        <div className="flex flex-col gap-4">
            <Toggle isSelected={onlyOpen} onChange={setOnlyOpen} label="Show only items that need your resolution" />
            {grouped.length === 0 && <p className="text-sm text-tertiary">No rules in this view.</p>}
            {grouped.map(([category, items]) => (
                <section key={category} aria-labelledby={`cat-${category}`} className="flex flex-col gap-2">
                    <h3 id={`cat-${category}`} className="text-sm font-semibold text-secondary">
                        {humanize(category)}
                    </h3>
                    <ul className="flex flex-col gap-2">
                        {items.map((r) => (
                            <RuleRow key={r.id} rule={r} canResolve={canResolve} onResolve={onResolve} />
                        ))}
                    </ul>
                </section>
            ))}
        </div>
    );
}

export function RuleRow({ rule: r, canResolve, onResolve }: { rule: CfpRule; canResolve: boolean; onResolve: (r: CfpRule) => void }) {
    const open = r.status === "needs_human_resolution";
    const modelProvider = ruleModelProvider(r);
    const last = r.resolutions[r.resolutions.length - 1];
    return (
        <li data-testid={`rule-${r.rule_key}`} data-status={r.status} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-primary">{humanize(r.rule_key)}</span>
                {r.track && <span className="text-xs text-tertiary">{r.track}</span>}
                {r.blocking && <span className="text-xs font-medium text-tertiary">Blocking</span>}
                <StatusBadge status={r.status} />
                {r.change_kind && r.change_kind !== "new" && <StatusBadge status={r.change_kind === "unchanged" ? "current" : "stale"} label={r.change_kind === "unchanged" ? "Unchanged in latest snapshot" : `Source ${r.change_kind}`} />}
            </div>
            <p className="text-sm text-primary">
                {r.value_text}
                {r.value && r.value !== r.value_text && <span className="text-tertiary"> (value: {r.value}{r.unit ? ` ${r.unit}` : ""})</span>}
            </p>
            <SourceQuote quote={r.quote} locator={r.locator} />
            <div className="flex flex-wrap items-center gap-2 text-xs text-tertiary">
                {r.methods.map((m) => (
                    <VerificationMethodLabel key={m} method={m} provider={m === "model_assisted" ? modelProvider : null} />
                ))}
                <span>{AGREEMENT[r.agreement] ?? r.agreement}</span>
                <span>· Independent check: {humanize(String(r.second_pass?.verdict ?? "not performed"))}</span>
            </div>
            {r.problems.length > 0 && (
                <ul className="list-disc pl-5 text-sm text-secondary" aria-label="Problems found">
                    {r.problems.map((p) => (
                        <li key={p}>{p}</li>
                    ))}
                </ul>
            )}
            {last && (
                <p className="text-sm text-secondary">
                    <span className="font-medium">Your resolution: {humanize(last.action)}.</span> {last.rationale}
                </p>
            )}
            {canResolve && (
                <div>
                    <Button size="sm" color={open ? "primary" : "secondary"} onClick={() => onResolve(r)} aria-label={`Resolve ${humanize(r.rule_key)}${r.track ? ` for ${r.track}` : ""}`}>
                        {open ? "Resolve" : "Change resolution"}
                    </Button>
                </div>
            )}
        </li>
    );
}
