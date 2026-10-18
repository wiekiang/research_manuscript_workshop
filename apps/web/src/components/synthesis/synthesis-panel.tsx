"use client";

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { ArtifactLink } from "@/components/research/provenance-link";
import { StatusBadge } from "@/components/research/status-badge";
import { api } from "@/lib/api/client";
import type { MapResult, MetaAnalysisResult, OverlapResult, ReviewAppendix, ReviewWorkspaceView } from "@/lib/api/types";
import { fmt, isStale, synthesisKindFor } from "@/lib/synthesis";
import { Refusal } from "./refusal";

function Stat({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex flex-col rounded-lg bg-primary p-3 ring-1 ring-secondary">
            <dt className="text-xs text-tertiary">{label}</dt>
            <dd className="font-semibold text-primary tabular-nums">{value}</dd>
        </div>
    );
}

export function MetaAnalysisView({ r }: { r: MetaAnalysisResult }) {
    if (r.status !== "computed") return <p className="text-sm text-warning-primary">Not performed: {r.detail}</p>;
    return (
        <dl data-testid="meta-analysis" className="grid gap-2 sm:grid-cols-4">
            <Stat label={`Pooled estimate (${r.effect_measure ?? "effect"})`} value={fmt(r.estimate)} />
            <Stat label="Standard error" value={fmt(r.se)} />
            <Stat label="95% CI" value={`${fmt(r.ci_low)} to ${fmt(r.ci_high)}`} />
            <Stat label="Studies (k)" value={String(r.k ?? "—")} />
            <Stat label="Q" value={fmt(r.q)} />
            <Stat label="df" value={String(r.df ?? "—")} />
            <Stat label="τ²" value={fmt(r.tau2)} />
            <Stat label="I²" value={`${fmt(r.i2, 2)}%`} />
            <p className="text-xs text-tertiary sm:col-span-4">
                Model: {r.model === "fixed" ? "fixed effect (inverse variance)" : "random effects (DerSimonian-Laird)"}. Computed by the platform ({r.engine}) from the
                extraction records.
            </p>
        </dl>
    );
}

export function MapView({ r }: { r: MapResult }) {
    return (
        <div data-testid="charting-map" className="flex flex-col gap-3">
            {Object.entries(r.dimensions).map(([dim, counts]) => (
                <table key={dim} className="w-full max-w-md text-left text-sm ring-1 ring-secondary">
                    <caption className="py-1 text-left text-xs font-medium text-secondary">{dim}</caption>
                    <tbody>
                        {Object.entries(counts).map(([cat, n]) => (
                            <tr key={cat} className="border-t border-secondary">
                                <td className="px-3 py-1">{cat}</td>
                                <td className="px-3 py-1 tabular-nums">{n}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            ))}
            {r.problems.length > 0 && (
                <ul className="list-disc pl-5 text-sm text-error-primary">
                    {r.problems.map((p) => (
                        <li key={p}>{p}</li>
                    ))}
                </ul>
            )}
            <p className="text-xs text-tertiary">
                {r.studies} studies charted ({r.engine}).
            </p>
        </div>
    );
}

export function OverlapView({ r }: { r: OverlapResult }) {
    if (r.status !== "computed") return <p className="text-sm text-warning-primary">Not performed: {r.detail}</p>;
    return (
        <dl data-testid="overlap" className="grid gap-2 sm:grid-cols-4">
            <Stat label="Corrected covered area (CCA)" value={fmt(r.cca, 3)} />
            <Stat label="Overlap level" value={r.level ?? "—"} />
            <Stat label="Reviews" value={String(r.reviews ?? "—")} />
            <Stat label="Unique primary studies" value={String(r.primary_studies ?? "—")} />
            <p className="text-xs text-tertiary sm:col-span-4">CCA = (N − r) / (r·c − r), computed by the platform ({r.engine}).</p>
        </dl>
    );
}

/** Platform-computed synthesis and the reproducibility appendix; stale results are flagged, never presented as current. */
export function SynthesisPanel({ projectId, view, canEdit, onChanged }: { projectId: string; view: ReviewWorkspaceView; canEdit: boolean; onChanged: () => void }) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();
    const [appendix, setAppendix] = useState<ReviewAppendix>();
    const kind = synthesisKindFor(view.specification);
    const stored = kind ? view.syntheses[kind] : view.syntheses.flow;
    const stale = kind ? isStale(view, kind) : isStale(view, "flow");

    const run = async (path: "synthesis" | "appendix") => {
        setBusy(true);
        setError(undefined);
        try {
            const r = await api.post<ReviewAppendix>(`/v1/projects/${projectId}/review/${path}`, {});
            if (path === "appendix") setAppendix(r);
            onChanged();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-4">
            {canEdit && (
                <div className="flex flex-wrap gap-2">
                    <Button size="sm" isLoading={busy} onClick={() => run("synthesis")}>
                        Compute synthesis
                    </Button>
                    <Button size="sm" color="secondary" isLoading={busy} onClick={() => run("appendix")}>
                        Generate reproducibility appendix
                    </Button>
                </div>
            )}
            <Refusal error={error} />
            {!stored && <p className="text-sm text-tertiary">No synthesis computed yet.</p>}
            {stored && (
                <div className="flex flex-col gap-2" data-testid="synthesis-result">
                    <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={stale ? "synthesis_stale" : "synthesis_current"} />
                        <ArtifactLink artifactId={stored.artifact_id} label="Synthesis record" />
                    </div>
                    {stale && (
                        <p data-testid="synthesis-stale" className="text-sm text-warning-primary">
                            Extraction records changed after this synthesis was computed. It is not current: compute it again before recording the synthesis stage.
                        </p>
                    )}
                    {kind === "meta_analysis" && <MetaAnalysisView r={stored.result as MetaAnalysisResult} />}
                    {kind === "map" && <MapView r={stored.result as MapResult} />}
                    {kind === "overlap" && <OverlapView r={stored.result as OverlapResult} />}
                    {!kind && <p className="text-sm text-tertiary">Narrative synthesis: record it in the synthesis stage; the platform stores the flow it is based on.</p>}
                </div>
            )}
            {appendix && (
                <div data-testid="appendix" className="flex flex-col gap-1 rounded-xl bg-secondary p-4 text-sm ring-1 ring-secondary">
                    <p className="font-medium text-primary">Reproducibility appendix ({appendix.reporting_standard})</p>
                    <p className="text-tertiary">
                        Protocol v{appendix.protocol.version}; {appendix.searches.length} search(es) with exact queries and dates; {appendix.flow.included} included studies.
                    </p>
                    <ArtifactLink artifactId={appendix.artifact_id} label="Download appendix" />
                </div>
            )}
        </div>
    );
}
