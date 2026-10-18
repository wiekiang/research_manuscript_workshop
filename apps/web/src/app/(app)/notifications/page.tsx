"use client";

import { Button } from "@/components/base/buttons/button";
import { ErrorAlert } from "@/components/research/error-alert";
import { Loading, PageHeader } from "@/components/research/page-header";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api/client";
import type { Notification } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cx } from "@/utils/cx";

export default function NotificationsPage() {
    const { data, error, isLoading, reload } = useResource<{ items: Notification[] }>("/v1/notifications");
    return (
        <div className="flex flex-col gap-8">
            <PageHeader title="Notifications" description="Approvals you need to give, changed official rules, budget thresholds and finished or failed work." />
            {isLoading && <Loading label="Loading notifications" />}
            <ErrorAlert error={error} />
            {data && data.items.length === 0 && <p className="text-sm text-tertiary">Nothing needs your attention.</p>}
            <ul className="flex flex-col gap-2">
                {data?.items.map((n) => (
                    <li key={n.id} className={cx("flex flex-col gap-1 rounded-xl p-4 ring-1 ring-secondary", n.read_at ? "bg-primary" : "bg-brand-primary")}>
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <a href={n.link ?? "#"} className="text-sm font-semibold text-primary hover:underline">
                                {n.title}
                                {!n.read_at && <span className="sr-only"> (unread)</span>}
                            </a>
                            <span className="text-xs text-tertiary">{formatDateTime(n.created_at)}</span>
                        </div>
                        {n.body && <p className="text-sm text-secondary">{n.body}</p>}
                        {!n.read_at && (
                            <div>
                                <Button
                                    size="sm"
                                    color="link-gray"
                                    onClick={async () => {
                                        await api.post(`/v1/notifications/${n.id}/read`);
                                        await reload();
                                    }}
                                >
                                    Mark as read
                                </Button>
                            </div>
                        )}
                    </li>
                ))}
            </ul>
        </div>
    );
}
