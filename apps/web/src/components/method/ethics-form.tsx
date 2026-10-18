"use client";

import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { NativeSelect } from "@/components/base/select/select-native";
import { TextArea } from "@/components/base/textarea/textarea";
import type { EthicsRights } from "@/lib/api/types";

export const EMPTY_ETHICS: EthicsRights = {
    involves_human_participants: false,
    personal_data: false,
    sensitive_data: false,
    restricted_datasets: false,
    data_licences: [],
    third_party_rights_notes: null,
    institutional_approval: { required: false, status: "not_applicable", body: null, reference: null },
    consent_procedure: null,
    deidentification_plan: null,
    declaration_text_accepted: false,
};

/**
 * Ethics, privacy and rights declaration. The platform never grants ethics approval: the researcher records what was
 * obtained (with its reference) and accepts the declaration text exactly as served by the API.
 */
export function EthicsForm({ value, onChange, declarationText }: { value: EthicsRights; onChange: (v: EthicsRights) => void; declarationText: string | undefined }) {
    const set = <K extends keyof EthicsRights>(k: K, v: EthicsRights[K]) => onChange({ ...value, [k]: v });
    const ia = value.institutional_approval;
    const setIa = (patch: Partial<EthicsRights["institutional_approval"]>) => set("institutional_approval", { ...ia, ...patch });
    return (
        <fieldset className="flex flex-col gap-3 rounded-xl p-4 ring-1 ring-secondary">
            <legend className="px-1 text-sm font-semibold text-secondary">Ethics, privacy and rights</legend>
            <div className="grid gap-2 sm:grid-cols-2">
                <Checkbox isSelected={value.involves_human_participants} onChange={(v) => set("involves_human_participants", v)} label="Involves human participants" />
                <Checkbox isSelected={value.personal_data} onChange={(v) => set("personal_data", v)} label="Uses personal data" />
                <Checkbox isSelected={value.sensitive_data} onChange={(v) => set("sensitive_data", v)} label="Uses sensitive data" />
                <Checkbox isSelected={value.restricted_datasets} onChange={(v) => set("restricted_datasets", v)} label="Uses restricted datasets" />
            </div>
            <Input
                label="Data licences or agreements (comma-separated)"
                value={value.data_licences.join(", ")}
                onChange={(v) => set("data_licences", v.split(",").map((x) => x.trim()).filter(Boolean))}
            />
            <TextArea label="Third-party rights notes" value={value.third_party_rights_notes ?? ""} onChange={(v) => set("third_party_rights_notes", v || null)} rows={2} />
            <div className="grid gap-3 sm:grid-cols-2">
                <NativeSelect
                    label="Institutional approval required"
                    value={ia.required ? "yes" : "no"}
                    onChange={(e) => setIa({ required: e.target.value === "yes" })}
                    options={[
                        { label: "No", value: "no" },
                        { label: "Yes", value: "yes" },
                    ]}
                />
                <NativeSelect
                    label="Approval status"
                    value={ia.status}
                    onChange={(e) => setIa({ status: e.target.value as EthicsRights["institutional_approval"]["status"] })}
                    options={[
                        { label: "Not applicable", value: "not_applicable" },
                        { label: "Not required (official reason recorded)", value: "not_required" },
                        { label: "Pending", value: "pending" },
                        { label: "Obtained", value: "obtained" },
                    ]}
                />
                <Input label="Approving body" value={ia.body ?? ""} onChange={(v) => setIa({ body: v || null })} />
                <Input label="Approval reference" value={ia.reference ?? ""} onChange={(v) => setIa({ reference: v || null })} />
            </div>
            <TextArea label="Consent procedure" value={value.consent_procedure ?? ""} onChange={(v) => set("consent_procedure", v || null)} rows={2} />
            <TextArea label="De-identification / handling plan" value={value.deidentification_plan ?? ""} onChange={(v) => set("deidentification_plan", v || null)} rows={2} />
            {declarationText ? (
                <>
                    <blockquote className="rounded-xl bg-secondary p-3 text-sm text-primary">{declarationText}</blockquote>
                    <Checkbox
                        isSelected={value.declaration_text_accepted}
                        onChange={(v) => set("declaration_text_accepted", v)}
                        label="I accept this ethics and rights declaration"
                    />
                </>
            ) : (
                <p className="text-xs text-tertiary">Save a first protocol version to load the exact declaration text from the server; you can then accept it in the next version.</p>
            )}
        </fieldset>
    );
}
