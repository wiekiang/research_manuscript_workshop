"use client";

import { UnavailableFeature } from "@/components/research/unavailable-feature";
import { workspaceBySegment } from "@/lib/features";

/** Renders the planned workspace for a segment from the single feature map, so labels never drift. */
export function WorkspacePlaceholder({ segment }: { segment: string }) {
    const w = workspaceBySegment(segment);
    if (!w) return null;
    return <UnavailableFeature title={w.label} milestone={w.milestone} summary={w.summary} />;
}
