import { Button } from "@/components/base/buttons/button";

export default function NotFound() {
    return (
        <main id="main-content" className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-6 px-4">
            <h1 className="font-display text-display-sm font-semibold text-primary">This page does not exist</h1>
            <p className="text-lg text-tertiary">The link may be out of date, or the item may belong to a workspace you are not signed in to.</p>
            <div>
                <Button size="lg" href="/dashboard">
                    Open the dashboard
                </Button>
            </div>
        </main>
    );
}
