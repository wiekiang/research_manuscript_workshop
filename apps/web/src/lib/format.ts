export function formatMoney(cents: number | null | undefined, currency = "USD"): string {
    const value = (cents ?? 0) / 100;
    return new Intl.NumberFormat("en", { style: "currency", currency }).format(value);
}

export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    try {
        return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone }).format(d);
    } catch {
        return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(d);
    }
}

export function formatUtc(iso: string | null | undefined): string {
    if (!iso) return "—";
    return `${formatDateTime(iso, "UTC")} UTC`;
}

/** Render an instant in the zone the source stated, when that zone is a fixed offset or IANA name we can represent. */
export function formatInStatedZone(iso: string | null | undefined, stated: string | null | undefined): string | null {
    if (!iso || !stated) return null;
    const key = stated.toUpperCase().replace(/[()]/g, "").trim();
    const fixed: Record<string, number> = { AOE: -12, "ANYWHERE ON EARTH": -12, UTC: 0, GMT: 0, PST: -8, PDT: -7, EST: -5, EDT: -4, CET: 1, CEST: 2, JST: 9 };
    let offset: number | undefined = fixed[key];
    const m = key.match(/^(?:UTC|GMT)\s*([+-])\s*(\d{1,2})$/);
    if (m) offset = (m[1] === "-" ? -1 : 1) * Number(m[2]);
    if (offset !== undefined) {
        const shifted = new Date(new Date(iso).getTime() + offset * 3600_000);
        return `${new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(shifted)} ${stated}`;
    }
    try {
        return `${formatDateTime(iso, stated)} ${stated}`;
    } catch {
        return null;
    }
}

export function relativeTime(iso: string | null | undefined): string {
    if (!iso) return "";
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
    if (Math.abs(diff) < 60) return rtf.format(-Math.round(diff), "second");
    if (Math.abs(diff) < 3600) return rtf.format(-Math.round(diff / 60), "minute");
    if (Math.abs(diff) < 86400) return rtf.format(-Math.round(diff / 3600), "hour");
    return rtf.format(-Math.round(diff / 86400), "day");
}

export function shortHash(h: string | null | undefined, n = 10): string {
    return h ? h.slice(0, n) : "—";
}

export function humanize(key: string): string {
    return key.replace(/[._]/g, " ").replace(/\s+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
