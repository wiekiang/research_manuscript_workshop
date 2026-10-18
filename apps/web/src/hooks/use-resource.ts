"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";

export interface Resource<T> {
    data: T | undefined;
    error: unknown;
    isLoading: boolean;
    reload: () => Promise<void>;
}

/** Fetch a JSON resource from the API; `path = null` skips the request. Optional polling interval in ms. */
export function useResource<T>(path: string | null, pollMs?: number): Resource<T> {
    const [data, setData] = useState<T>();
    const [error, setError] = useState<unknown>();
    const [isLoading, setLoading] = useState<boolean>(!!path);
    const current = useRef(path);
    current.current = path;

    const reload = useCallback(async () => {
        if (!current.current) return;
        const requested = current.current;
        try {
            const result = await api.get<T>(requested);
            if (current.current === requested) {
                setData(result);
                setError(undefined);
            }
        } catch (err) {
            if (current.current === requested) setError(err);
        } finally {
            if (current.current === requested) setLoading(false);
        }
    }, []);

    useEffect(() => {
        setLoading(!!path);
        setData(undefined);
        void reload();
    }, [path, reload]);

    useEffect(() => {
        if (!path || !pollMs) return;
        const id = setInterval(() => void reload(), pollMs);
        return () => clearInterval(id);
    }, [path, pollMs, reload]);

    return { data, error, isLoading, reload };
}
