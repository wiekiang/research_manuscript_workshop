"use client";

import { useEffect, useState } from "react";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import { ApprovalPanel } from "@/components/research/approval-panel";
import { Section } from "@/components/research/page-header";
import { api } from "@/lib/api/client";
import type { MethodInstance, OpportunityEntry, TransitionResult } from "@/lib/api/types";

interface Props {
    projectId: string;
    opportunities: OpportunityEntry[];
    instance: MethodInstance | null;
    declaration: string | undefined;
    onApproved: () => void;
}

const MIN_DIFF = 40;

/**
 * H1: the researcher's own decision on the question, intended contribution and method. The reasoning fields are
 * written by the researcher (never prefilled with agent text); the API re-checks every precondition and returns its
 * reasons verbatim when one is missing.
 */
export function DirectionApproval({ projectId, opportunities, instance, declaration, onApproved }: Props) {
    const [oppId, setOppId] = useState(opportunities[0]?.id ?? "");
    const opp = opportunities.find((o) => o.id === oppId);
    const [question, setQuestion] = useState("");
    const [contribution, setContribution] = useState("");
    const [differs, setDiffers] = useState("");
    const [methodRationale, setMethodRationale] = useState("");
    const [feasRationale, setFeasRationale] = useState("");
    const [rationaleApproved, setRationaleApproved] = useState(false);

    useEffect(() => {
        // The proposal's question is a starting point the researcher edits; their reasoning fields start empty.
        setQuestion(opp?.rationale?.research_question ?? opp?.research_question ?? "");
        setContribution(opp?.rationale?.intended_contribution ?? "");
    }, [opp?.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const local: string[] = [];
    if (!instance) local.push("select a study type and venue category");
    if (!opp) local.push("choose one of the project's opportunity proposals");
    if (question.trim().length < 10) local.push("state the research question (at least 10 characters)");
    if (contribution.trim().length < 10) local.push("state the intended contribution (at least 10 characters)");
    if (differs.trim().length < MIN_DIFF) local.push("explain in your own words how this differs from the nearest prior work");
    if (methodRationale.trim().length < 20) local.push("explain why the selected study type can answer the question");
    if (opp?.rationale?.status === "draft" && !rationaleApproved) local.push("edit the Paper Rationale or explicitly approve its reasoning");
    const feasStatus = opp?.feasibility?.status;
    if (feasStatus && feasStatus !== "feasible" && feasRationale.trim().length < 20) local.push(`feasibility is ${feasStatus}: record why you proceed`);

    return (
        <Section title="Direction decision (H1)" description="Your decision on the research question, intended contribution and method. Proposals are advisory; this is the decision.">
            <div className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
                <NativeSelect
                    label="Proposal you are building on"
                    value={oppId}
                    onChange={(e) => setOppId(e.target.value)}
                    options={opportunities.map((o) => ({ label: o.title, value: o.id }))}
                />
                {opp && (
                    <p className="text-xs text-tertiary">
                        Novelty caveat: {opp.novelty_caveat} · Paper Rationale status: {opp.rationale?.status ?? "missing"} · Feasibility (advisory): {feasStatus ?? "missing"}
                    </p>
                )}
                <TextArea label="Research question" isRequired value={question} onChange={setQuestion} rows={2} />
                <TextArea label="Intended contribution" isRequired value={contribution} onChange={setContribution} rows={2} />
                <TextArea
                    label="How it differs from the nearest prior work (your own words)"
                    isRequired
                    hint={`At least ${MIN_DIFF} characters. This is recorded as your rationale for H1.`}
                    value={differs}
                    onChange={setDiffers}
                    rows={3}
                />
                <TextArea label="Why this study type can answer the question" isRequired value={methodRationale} onChange={setMethodRationale} rows={2} />
                {feasStatus && feasStatus !== "feasible" && (
                    <TextArea label="Why you proceed despite the feasibility estimate" isRequired value={feasRationale} onChange={setFeasRationale} rows={2} />
                )}
                {opp?.rationale?.status === "draft" && (
                    <Checkbox
                        isSelected={rationaleApproved}
                        onChange={setRationaleApproved}
                        label="I reviewed the agent-drafted Paper Rationale and approve its reasoning"
                        hint="Or edit it on the proposal card above; your edited version is then used."
                    />
                )}
            </div>
            <ApprovalPanel
                gate="H1"
                title="Record the research direction"
                declaration={declaration ?? ""}
                blockingReasons={declaration ? local : ["the H1 declaration could not be loaded", ...local]}
                submitLabel="Sign H1 and continue to the protocol"
                onSubmit={async (b) => {
                    await api.post<{ transition: TransitionResult }>(`/v1/projects/${projectId}/direction/approve`, {
                        opportunity_id: oppId,
                        research_question: question.trim(),
                        intended_contribution: contribution.trim(),
                        how_it_differs: differs.trim(),
                        method_rationale: methodRationale.trim(),
                        rationale_approved: rationaleApproved,
                        feasibility_rationale: feasRationale.trim() || null,
                        declaration_accepted: b.declaration_accepted,
                        declaration_text: b.declaration_text,
                    });
                    onApproved();
                }}
            />
        </Section>
    );
}
