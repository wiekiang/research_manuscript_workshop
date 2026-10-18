"use client";

import { useEffect } from "react";
import { BadgeWithDot } from "@/components/base/badges/badges";
import { useResource } from "@/hooks/use-resource";
import type { ModelProviderView } from "@/lib/api/types";
import { PROVIDER_CHANGED_EVENT, providerBadgeLabel } from "@/lib/model-provider";

/** Project shell badge: whether AI output in this project is real (and from which provider) or recorded. */
export function ProviderBadge({ projectId, tick }: { projectId: string; tick?: number }) {
    const view = useResource<ModelProviderView>(`/v1/projects/${projectId}/model-provider`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(() => void view.reload(), [tick]);
    useEffect(() => {
        const onChange = (e: Event) => {
            if ((e as CustomEvent<{ projectId: string }>).detail?.projectId === projectId) void view.reload();
        };
        window.addEventListener(PROVIDER_CHANGED_EVENT, onChange);
        return () => window.removeEventListener(PROVIDER_CHANGED_EVENT, onChange);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [projectId]);
    if (view.error) return null;
    const color = !view.data?.selected ? "gray" : view.data.selected === "fixture" ? "warning" : "brand";
    return (
        <a href={`/projects/${projectId}/costs#ai-provider`} className="outline-focus-ring focus-visible:outline-2" data-testid="provider-badge">
            <BadgeWithDot type="pill-color" color={color} size="sm">
                {providerBadgeLabel(view.data)}
            </BadgeWithDot>
        </a>
    );
}
