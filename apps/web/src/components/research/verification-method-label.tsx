import { CpuChip01, Settings04, User01 } from "@untitledui/icons";
import { cx } from "@/utils/cx";

const METHODS: Record<string, { label: string; description: string; icon: typeof User01 }> = {
    deterministic: { label: "Deterministic", description: "Rule-based check with no model involved", icon: Settings04 },
    model_assisted: { label: "Model-assisted", description: "Produced or checked with a language model; not human verification", icon: CpuChip01 },
    human: { label: "Human", description: "Confirmed by a researcher", icon: User01 },
};

interface Props {
    method: string;
    /** Model provider, when known. The fixture provider is labelled as test/demo output. */
    provider?: string | null;
    className?: string;
}

export function VerificationMethodLabel({ method, provider, className }: Props) {
    const spec = METHODS[method] ?? { label: method.replace(/_/g, " "), description: method, icon: Settings04 };
    const Icon = spec.icon;
    const fixture = provider === "fixture";
    return (
        <span
            className={cx(
                "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-secondary ring-inset",
                method === "human" ? "text-success-primary" : "text-secondary",
                className,
            )}
            title={spec.description}
        >
            <Icon className="size-3.5" aria-hidden="true" />
            {spec.label}
            {fixture && <span className="text-utility-amber-700"> · Fixture output (test/demo only)</span>}
        </span>
    );
}

export function FixtureNotice({ provider }: { provider?: string | null }) {
    if (provider !== "fixture") return null;
    return (
        <p className="rounded-md bg-warning-primary px-2 py-1 text-xs text-utility-amber-700">
            Fixture output (test/demo only). These results were replayed from a recorded test response, not produced by a configured model.
        </p>
    );
}
