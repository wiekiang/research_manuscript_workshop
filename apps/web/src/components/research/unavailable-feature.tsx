import { Lock01 } from "@untitledui/icons";
import { FeaturedIcon } from "@/components/foundations/featured-icon/featured-icon";
import { cx } from "@/utils/cx";

interface Props {
    title: string;
    milestone: string;
    summary: string;
    className?: string;
}

/** A workspace that is part of the product plan but not enabled in this release. Never shows sample data. */
export function UnavailableFeature({ title, milestone, summary, className }: Props) {
    return (
        <section aria-labelledby="unavailable-title" className={cx("flex flex-col items-start gap-4 rounded-2xl border border-dashed border-primary p-8", className)}>
            <FeaturedIcon icon={Lock01} color="gray" theme="modern" size="lg" />
            <div className="flex flex-col gap-1">
                <h2 id="unavailable-title" className="font-display text-xl font-semibold text-primary">
                    {title}
                </h2>
                <p className="text-sm font-medium text-secondary">Not available in this release. Planned for milestone {milestone}.</p>
                <p className="max-w-prose text-sm text-tertiary">{summary}</p>
            </div>
            <p className="text-xs text-tertiary">Nothing here is simulated: this workspace stays empty until its checks and safeguards are implemented and tested.</p>
        </section>
    );
}
