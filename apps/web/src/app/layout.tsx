import type { Metadata, Viewport } from "next";
import { Inter, Source_Serif_4 } from "next/font/google";
import { RouteProvider } from "@/providers/router-provider";
import { SessionProvider } from "@/providers/session";
import { Theme } from "@/providers/theme";
import "@/styles/globals.css";
import { cx } from "@/utils/cx";
import { PRODUCT_NAME } from "@/lib/brand";

const inter = Inter({ subsets: ["latin"], display: "swap", variable: "--font-inter" });
const serif = Source_Serif_4({ subsets: ["latin"], display: "swap", variable: "--font-serif" });

export const metadata: Metadata = {
    title: { default: PRODUCT_NAME, template: `%s · ${PRODUCT_NAME}` },
    description: "From Call for Papers to Submission-Ready Manuscripts.",
};

export const viewport: Viewport = {
    themeColor: "#1e6b60",
    colorScheme: "light dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
    return (
        <html lang="en" suppressHydrationWarning>
            <body className={cx(inter.variable, serif.variable, "bg-primary antialiased")}>
                {/* Focus anchor used to reset the sequential focus starting point after client-side navigation. */}
                <span id="focus-reset" tabIndex={-1} aria-hidden="true" className="sr-only" />
                <a
                    href="#main-content"
                    className="sr-only z-50 rounded-md bg-brand-solid px-3 py-2 text-sm font-semibold text-white focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
                >
                    Skip to main content
                </a>
                <RouteProvider>
                    <Theme>
                        <SessionProvider>{children}</SessionProvider>
                    </Theme>
                </RouteProvider>
            </body>
        </html>
    );
}
