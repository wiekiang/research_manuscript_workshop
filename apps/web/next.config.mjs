/** @type {import('next').NextConfig} */
const apiOrigin = process.env.RP_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig = {
    experimental: {
        optimizePackageImports: ["@untitledui/icons"],
        // Uploads are proxied to the API, which enforces the real per-kind limits (templates 50 MB,
        // contribution files 200 MB). Next buffers proxied bodies and would otherwise truncate at 10 MB.
        proxyClientMaxBodySize: "210mb",
    },
    // Same-origin proxy so the API's httpOnly session cookies and CSRF cookie apply to the browser app.
    async rewrites() {
        return [
            { source: "/v1/:path*", destination: `${apiOrigin}/v1/:path*` },
            { source: "/.well-known/:path*", destination: `${apiOrigin}/.well-known/:path*` },
        ];
    },
};

export default nextConfig;
