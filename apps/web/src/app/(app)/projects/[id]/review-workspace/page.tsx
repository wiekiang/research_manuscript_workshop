"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { useProject } from "@/components/project/project-context";
import { Loading, Section } from "@/components/research/page-header";
import { StatusBadge } from "@/components/research/status-badge";
import { ExtractionDialog } from "@/components/synthesis/extraction-dialog";
import { FlowDiagram } from "@/components/synthesis/flow-diagram";
import { RecordsTable } from "@/components/synthesis/records-table";
import { Refusal } from "@/components/synthesis/refusal";
import { SynthesisPanel } from "@/components/synthesis/synthesis-panel";
import { useResource } from "@/hooks/use-resource";
import { ApiError, api } from "@/lib/api/client";
import type { EvidenceGraph, ReviewRecord, ReviewWorkspaceView } from "@/lib/api/types";
import { formatDateTime, humanize, shortHash } from "@/lib/format";
import { SETUP_CODES, SYNTHESIS_LABEL } from "@/lib/synthesis";

const DONE = ["succeeded", "partial", "failed"];

export default function ReviewWorkspacePage() {
    const { project, taskTick, reload } = useProject();
    const pid = project?.id ?? "";
    const view = useResource<ReviewWorkspaceView>(pid ? `/v1/projects/${pid}/review` : null);
    const evidence = useResource<EvidenceGraph>(pid ? `/v1/projects/${pid}/evidence` : null);
    const [busy, setBusy] = useState(false);
    const [runError, setRunError] = useState<unknown>();
    const [extracting, setExtracting] = useState<ReviewRecord | null>(null);
    const running = (view.data?.searches ?? []).some((s) => !DONE.includes(s.status));
    const reloadAll = () => void Promise.all([view.reload(), evidence.reload(), reload()]);

    useEffect(() => {
        reloadAll();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!running) return;
        const id = setInterval(reloadAll, 2000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [running]);

    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    const setup = view.error instanceof ApiError && SETUP_CODES.includes(view.error.code);
    const v = view.data;
    const spec = v?.specification;

    const runSearches = async () => {
        setBusy(true);
        setRunError(undefined);
        try {
            await api.post(`/v1/projects/${pid}/review/searches`, {});
            reloadAll();
        } catch (err) {
            setRunError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="flex flex-col gap-10">
            <Section
                title="Review workspace"
                description="Protocol-bound searches, human screening with the protocol's exclusion reasons, passage-linked extraction and appraisal, and a synthesis computed by the platform. Counts come from stored records only."
            >
                {view.isLoading && !v && <Loading label="Loading the review workspace" />}
                {view.error != null && <Refusal error={view.error} tone={setup ? "notice" : "error"} />}
                {spec && v && (
                    <div data-testid="review-spec-summary" className="flex flex-col gap-1 rounded-xl bg-primary p-4 text-sm ring-1 ring-secondary">
                        <p className="font-medium text-primary">
                            {humanize(spec.review_type)}: {spec.question}
                        </p>
                        <p className="text-tertiary">
                            {SYNTHESIS_LABEL[spec.synthesis]}
                            {spec.effect_measure ? ` · ${spec.effect_measure}` : ""}
                            {spec.pooling_model ? ` · ${spec.pooling_model === "fixed" ? "fixed effect" : "random effects (DerSimonian-Laird)"}` : ""} · reporting standard{" "}
                            {spec.reporting_standard}
                        </p>
                        <p className="text-xs text-tertiary">Frozen with protocol {shortHash(v.protocol_hash)}. Changing it requires a protocol amendment.</p>
                    </div>
                )}
            </Section>

            {spec && v && (
                <>
                    <Section
                        title="Specified searches"
                        description="Each search runs exactly as written in the frozen specification."
                        actions={
                            canEdit && (
                                <Button size="sm" isLoading={busy} onClick={runSearches}>
                                    Run specified searches
                                </Button>
                            )
                        }
                    >
                        <Refusal error={runError} />
                        <ul className="flex flex-col gap-2">
                            {spec.searches.map((s, i) => {
                                const runs = v.searches.filter((r) => r.query === s.query && r.providers.includes(s.provider));
                                return (
                                    <li key={i} data-testid="review-search" className="flex flex-col gap-1 rounded-xl bg-primary p-3 text-sm ring-1 ring-secondary">
                                        <p className="font-medium text-primary">
                                            {s.provider}: <code>{s.query}</code>
                                        </p>
                                        <p className="text-xs text-tertiary">
                                            Years {s.year_from ?? "any"}–{s.year_to ?? "any"} · up to {s.max_results} records
                                        </p>
                                        {runs.length === 0 && <p className="text-xs text-tertiary">Not executed yet.</p>}
                                        {runs.map((r) => (
                                            <p key={r.id} className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                                                <StatusBadge status={r.status} />
                                                {r.executed_at ? `Executed ${formatDateTime(r.executed_at)}` : "Waiting to execute"}
                                                {r.retrieved != null && ` · ${r.retrieved} retrieved`}
                                            </p>
                                        ))}
                                    </li>
                                );
                            })}
                        </ul>
                    </Section>

                    <Section title="Study flow" description="PRISMA-style counts derived from the stored search and screening records.">
                        <FlowDiagram flow={v.flow} />
                    </Section>

                    <Section title="Screening and extraction" description="Screening decisions are made by researchers. Exclusions use only the protocol's reasons.">
                        <RecordsTable
                            projectId={pid}
                            records={v.records}
                            spec={spec}
                            includedIds={v.flow.included_ids}
                            canEdit={canEdit}
                            onChanged={reloadAll}
                            onExtract={setExtracting}
                        />
                    </Section>

                    <Section title="Synthesis" description="Computed deterministically by the platform from the current extraction records.">
                        <SynthesisPanel projectId={pid} view={v} canEdit={canEdit} onChanged={reloadAll} />
                    </Section>

                    <ExtractionDialog
                        key={extracting?.paper_id ?? "none"}
                        projectId={pid}
                        record={extracting}
                        spec={spec}
                        passages={evidence.data?.passages ?? []}
                        onOpenChange={(o) => !o && setExtracting(null)}
                        onSaved={reloadAll}
                    />
                </>
            )}
        </div>
    );
}
