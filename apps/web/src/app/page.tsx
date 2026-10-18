import { PenTool02 } from "@untitledui/icons";
import { Button } from "@/components/base/buttons/button";
import { COPY } from "@/lib/copy";
import { PRODUCT_NAME } from "@/lib/brand";

const PATH: { stage: string; detail: string; human?: string }[] = [
    { stage: "Official call for papers", detail: "Import the CFP, check every extracted rule against its source sentence.", human: "You confirm the track rules" },
    { stage: "Research direction", detail: "Gap evidence, nearest prior work and an honest feasibility estimate.", human: "H1 — you decide the question" },
    { stage: "Protocol", detail: "A frozen, method-specific plan with ethics and rights declared.", human: "H2 — you freeze it" },
    { stage: "Your research", detail: "You run or supply the study; every result keeps its provenance and assurance level." },
    { stage: "Outcomes", detail: "Actual results compared with what the paper set out to show.", human: "H3 — you interpret them" },
    { stage: "Manuscript and review", detail: "Evidence-linked drafting, independent critique and venue compliance checks." },
    { stage: "Submission package", detail: "The official template, compiled and checked, for you to submit yourself.", human: "H4 — every author signs" },
];

export default function Home() {
    return (
        <div className="min-h-dvh bg-primary">
            <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-8">
                <span className="font-display text-lg font-semibold text-primary">{PRODUCT_NAME}</span>
                <nav aria-label="Account" className="flex gap-3">
                    <Button color="tertiary" size="md" href="/login">
                        Sign in
                    </Button>
                    <Button color="primary" size="md" href="/register">
                        Create an account
                    </Button>
                </nav>
            </header>
            <main id="main-content" className="mx-auto grid max-w-6xl gap-12 px-4 pt-10 pb-20 sm:px-8 lg:grid-cols-[1.1fr_1fr] lg:gap-16 lg:pt-16">
                <section aria-labelledby="hero-title" className="flex flex-col gap-6">
                    <h1 id="hero-title" className="font-display text-display-md font-semibold tracking-tight text-primary md:text-display-lg">
                        {COPY.home_headline}
                    </h1>
                    <p className="max-w-xl text-xl text-secondary">{COPY.home_subhead}</p>
                    <p data-testid="responsibility-message" className="max-w-xl border-l-4 border-utility-amber-400 pl-4 text-md text-secondary">
                        {COPY.responsibility_message}
                    </p>
                    <div className="flex flex-wrap gap-3">
                        <Button size="xl" href="/register">
                            Start a project
                        </Button>
                        <Button size="xl" color="secondary" href="/login">
                            Sign in
                        </Button>
                    </div>
                    <p className="max-w-xl text-sm text-tertiary">{COPY.submission_ready_definition}</p>
                </section>
                <section aria-labelledby="path-title" className="rounded-2xl bg-secondary_subtle p-6 ring-1 ring-secondary sm:p-8">
                    <h2 id="path-title" className="font-display text-lg font-semibold text-primary">
                        The path to a submission
                    </h2>
                    <p className="mt-1 text-sm text-tertiary">Agents do the repeatable work. Every consequential decision waits for your signature.</p>
                    <ol className="mt-6 flex flex-col">
                        {PATH.map((p, i) => (
                            <li key={p.stage} className="relative flex gap-4 pb-5 last:pb-0">
                                {i < PATH.length - 1 && <span aria-hidden="true" className="absolute top-7 left-3 h-full w-px bg-border-secondary" />}
                                <span
                                    className={
                                        p.human
                                            ? "z-10 flex size-6 shrink-0 items-center justify-center rounded-full bg-warning-primary ring-1 ring-utility-amber-400"
                                            : "z-10 mt-1.5 ml-1.5 size-3 shrink-0 rounded-full bg-brand-solid"
                                    }
                                >
                                    {p.human && <PenTool02 className="size-3.5 text-fg-warning-primary" aria-hidden="true" />}
                                </span>
                                <div className="flex flex-col gap-0.5">
                                    <p className="text-md font-semibold text-primary">{p.stage}</p>
                                    <p className="text-sm text-tertiary">{p.detail}</p>
                                    {p.human && <p className="text-sm font-medium text-utility-amber-700">{p.human}</p>}
                                </div>
                            </li>
                        ))}
                    </ol>
                </section>
            </main>
        </div>
    );
}
