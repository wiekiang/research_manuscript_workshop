"use client";

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TaskProgress } from "@/components/cfp/task-progress";
import { ClaimDetail, ClaimStatusBadge } from "@/components/evidence/claim-detail";
import { CreateClaimDialog } from "@/components/evidence/create-claim-dialog";
import { PassageQuote } from "@/components/evidence/passage-quote";
import { useProject } from "@/components/project/project-context";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, Section } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { EvidenceGraph, PaperEntry, PassageEntry, Task } from "@/lib/api/types";
import { CATEGORY_LABEL } from "@/lib/literature";

const TASKS = new Set(["evidence_extraction", "claim_support_check"]);

export default function EvidenceWorkspace() {
    const { project, taskTick } = useProject();
    const pid = project?.id ?? "";
    const graph = useResource<EvidenceGraph>(pid ? `/v1/projects/${pid}/evidence` : null);
    const papers = useResource<{ items: PaperEntry[] }>(pid ? `/v1/projects/${pid}/papers` : null);
    const tasks = useResource<{ items: Task[] }>(pid ? `/v1/projects/${pid}/tasks?limit=30` : null);
    const [openClaim, setOpenClaim] = useState<string | null>(null);
    const [creating, setCreating] = useState(false);
    const [reassess, setReassess] = useState<{ busy: boolean; result?: string; error?: unknown }>({ busy: false });
    const evTasks = (tasks.data?.items ?? []).filter((t) => TASKS.has(t.kind));
    const active = evTasks.some((t) => ["queued", "running", "failed_retryable"].includes(t.state));
    const reloadAll = () => void Promise.all([graph.reload(), papers.reload(), tasks.reload()]);

    useEffect(() => {
        reloadAll();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskTick]);
    useEffect(() => {
        if (!active) return;
        const id = setInterval(reloadAll, 2000);
        return () => clearInterval(id);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active]);

    const paperMap = useMemo(() => new Map((papers.data?.items ?? []).map((p) => [p.id, p])), [papers.data]);
    const passageMap = useMemo(() => new Map((graph.data?.passages ?? []).map((p) => [p.id, p])), [graph.data]);
    if (!project) return null;
    const canEdit = project.my_role === "owner" || project.my_role === "coauthor";
    const g = graph.data;
    const byPaper = new Map<string, PassageEntry[]>();
    for (const p of g?.passages ?? []) {
        const list = byPaper.get(p.paper_id) ?? [];
        list.push(p);
        byPaper.set(p.paper_id, list);
    }
    const claim = g?.claims.find((c) => c.id === openClaim);
    return (
        <div className="flex flex-col gap-10">
            <TaskProgress tasks={evTasks} title="Evidence processing" />
            {graph.isLoading && !g && <Loading label="Loading evidence" />}
            <ErrorAlert error={graph.error} />
            {g && (
                <>
                    <Section
                        title="Claim registry"
                        description={
                            <>
                                Claim status is set only by the platform's verification policy (active version <strong data-testid="policy-version">{g.policy.version}</strong>). “Meets verification policy”
                                is not a certification of scientific truth. Each verification record says whether it was deterministic, model-assisted or human.
                            </>
                        }
                        actions={
                            canEdit && (
                                <>
                                    <Button size="sm" onClick={() => setCreating(true)}>
                                        Register claim
                                    </Button>
                                    <Button
                                        size="sm"
                                        color="secondary"
                                        isLoading={reassess.busy}
                                        onClick={async () => {
                                            setReassess({ busy: true });
                                            try {
                                                const r = await api.post<{ policy: string; kept_with_proof: number; reopened: number }>(`/v1/projects/${pid}/claims/reassess`, {});
                                                setReassess({ busy: false, result: `Reassessed under ${r.policy}: ${r.kept_with_proof} kept with proof, ${r.reopened} reopened.` });
                                                reloadAll();
                                            } catch (err) {
                                                setReassess({ busy: false, error: err });
                                            }
                                        }}
                                    >
                                        Reassess claims under current policy
                                    </Button>
                                </>
                            )
                        }
                    >
                        {reassess.result && <p className="text-sm text-success-primary">{reassess.result}</p>}
                        <ErrorAlert error={reassess.error} />
                        {g.claims.length === 0 && <p className="text-sm text-tertiary">No claims registered yet.</p>}
                        <ul className="flex flex-col gap-2">
                            {g.claims.map((c) => (
                                <li key={c.id} data-testid="claim-row" data-status={c.status} data-category={c.category} className="flex flex-col gap-2 rounded-xl bg-primary p-4 ring-1 ring-secondary sm:flex-row sm:items-center sm:justify-between">
                                    <div className="flex min-w-0 flex-col gap-1">
                                        <span className="text-sm text-primary">
                                            <span className="font-mono text-xs text-tertiary">{c.claim_key}</span> {c.proposition}
                                        </span>
                                        <span className="flex flex-wrap items-center gap-2 text-xs text-tertiary">
                                            <ClaimStatusBadge claim={c} />
                                            {c.kind.replace("_", " ")} · {CATEGORY_LABEL[c.category] ?? c.category}
                                            {c.critical && <span className="font-medium text-warning-primary">critical</span>}
                                            {c.gate_eligible ? "· usable at gates" : "· not usable at gates"}
                                            {c.supersedes_id && "· revision"}
                                        </span>
                                    </div>
                                    <Button size="sm" color="secondary" onClick={() => setOpenClaim(c.id)}>
                                        Details
                                    </Button>
                                </li>
                            ))}
                        </ul>
                    </Section>
                    <Section title="Evidence passages" description="Passages are quoted verbatim and re-verified against the stored source text by the platform. Unverified passages cannot satisfy passage requirements.">
                        {g.passages.length === 0 && <p className="text-sm text-tertiary">No passages yet. Upload a paper or request permitted full text in the literature workspace.</p>}
                        {[...byPaper.entries()].map(([paperId, list]) => (
                            <article key={paperId} className="flex flex-col gap-3 rounded-xl bg-primary p-4 ring-1 ring-secondary">
                                <h3 className="text-sm font-semibold text-primary">{paperMap.get(paperId)?.title ?? "Paper"}</h3>
                                <ul className="flex flex-col gap-3">
                                    {list.map((p) => (
                                        <li key={p.id}>
                                            <PassageQuote passage={p} />
                                        </li>
                                    ))}
                                </ul>
                            </article>
                        ))}
                    </Section>
                </>
            )}
            {creating && <CreateClaimDialog projectId={pid} onClose={() => setCreating(false)} onDone={reloadAll} />}
            {claim && g && (
                <ClaimDetail
                    claim={claim}
                    passages={passageMap}
                    papers={paperMap}
                    requirements={g.policy.requirements}
                    policyVersion={g.policy.version}
                    canEdit={canEdit}
                    onClose={() => setOpenClaim(null)}
                    onChanged={reloadAll}
                />
            )}
        </div>
    );
}
