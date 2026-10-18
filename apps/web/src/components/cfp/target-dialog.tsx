"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { NativeSelect } from "@/components/base/select/select-native";
import { DialogShell } from "@/components/research/dialog";
import { ErrorAlert } from "@/components/research/error-alert";
import { api } from "@/lib/api/client";
import type { EditionView } from "@/lib/api/types";

interface Props {
    isOpen: boolean;
    onClose: () => void;
    projectId: string;
    projectVersion: number;
    editions: EditionView[];
    onSelected: () => void;
}

export function TargetDialog({ isOpen, onClose, projectId, projectVersion, editions, onSelected }: Props) {
    const [editionId, setEditionId] = useState(editions[0]?.edition.id ?? "");
    const edition = editions.find((e) => e.edition.id === editionId);
    const [trackId, setTrackId] = useState("");
    const [mode, setMode] = useState<"official" | "exploratory">("official");
    const [confirmed, setConfirmed] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>();

    useEffect(() => {
        if (!editionId && editions[0]) setEditionId(editions[0].edition.id);
    }, [editions, editionId]);
    useEffect(() => setTrackId(""), [editionId]);

    const submit = async () => {
        setBusy(true);
        setError(undefined);
        try {
            await api.post(`/v1/projects/${projectId}/target`, {
                edition_id: editionId,
                track_id: trackId || null,
                mode,
                official_source_confirmed: confirmed,
                expected_version: projectVersion,
            });
            onSelected();
            onClose();
        } catch (err) {
            setError(err);
        } finally {
            setBusy(false);
        }
    };

    return (
        <DialogShell
            isOpen={isOpen}
            onOpenChange={(o) => !o && onClose()}
            title="Select your target track"
            description="Compliance checks and the official template use this edition and track. An exploratory target lets you keep planning but blocks the CFP gate."
            footer={
                <>
                    <Button color="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button isLoading={busy} isDisabled={!editionId || (mode === "official" && (!trackId || !confirmed))} onClick={submit}>
                        Select target
                    </Button>
                </>
            }
        >
            <NativeSelect label="Conference edition" value={editionId} onChange={(e) => setEditionId(e.target.value)} options={editions.map((e) => ({ label: e.edition.name, value: e.edition.id }))} />
            <NativeSelect
                label="Track"
                value={trackId}
                onChange={(e) => setTrackId(e.target.value)}
                options={[{ label: "Choose a track", value: "" }, ...(edition?.tracks ?? []).map((t) => ({ label: t.name, value: t.id }))]}
            />
            <NativeSelect
                label="Target type"
                value={mode}
                onChange={(e) => setMode(e.target.value as "official" | "exploratory")}
                options={[
                    { label: "Official: I will submit to this track", value: "official" },
                    { label: "Exploratory: planning only", value: "exploratory" },
                ]}
            />
            {mode === "official" && (
                <Checkbox
                    isSelected={confirmed}
                    onChange={setConfirmed}
                    label="The snapshot comes from the organizer's official CFP page"
                    hint="The platform records your confirmation; it cannot verify official status on its own."
                />
            )}
            <ErrorAlert error={error} />
        </DialogShell>
    );
}
