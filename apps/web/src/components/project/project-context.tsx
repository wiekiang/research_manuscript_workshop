"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useResource } from "@/hooks/use-resource";
import type { Project } from "@/lib/api/types";

interface ProjectValue {
    project: Project | undefined;
    error: unknown;
    isLoading: boolean;
    reload: () => Promise<void>;
    /** Increments whenever the live stream reports a project event; pages reload their own data on change. */
    eventTick: number;
    /** Increments whenever task state changes. */
    taskTick: number;
    live: "connecting" | "live" | "offline";
}

/** Exported for components that render both inside and outside a project (they read it optionally). */
export const ProjectContext = createContext<ProjectValue | null>(null);

export function ProjectProvider({ projectId, children }: { projectId: string; children: ReactNode }) {
    const { data, error, isLoading, reload } = useResource<Project>(`/v1/projects/${projectId}`);
    const [eventTick, setEventTick] = useState(0);
    const [taskTick, setTaskTick] = useState(0);
    const [live, setLive] = useState<ProjectValue["live"]>("connecting");

    const reloadAll = useCallback(async () => {
        await reload();
    }, [reload]);

    useEffect(() => {
        if (typeof EventSource === "undefined") {
            setLive("offline");
            return;
        }
        // EventSource reconnects on its own and resumes from Last-Event-ID; a page reload refetches state.
        const es = new EventSource(`/v1/projects/${projectId}/stream`, { withCredentials: true });
        es.onopen = () => setLive("live");
        es.onerror = () => setLive("offline");
        es.addEventListener("project", () => {
            setEventTick((t) => t + 1);
            void reload();
        });
        es.addEventListener("tasks", () => setTaskTick((t) => t + 1));
        return () => es.close();
    }, [projectId, reload]);

    return (
        <ProjectContext.Provider value={{ project: data, error, isLoading, reload: reloadAll, eventTick, taskTick, live }}>{children}</ProjectContext.Provider>
    );
}

export function useProject(): ProjectValue {
    const v = useContext(ProjectContext);
    if (!v) throw new Error("useProject must be used inside ProjectProvider");
    return v;
}
