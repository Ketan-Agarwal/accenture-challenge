import type { NextConfig } from "next";

const apiOrigin = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // TypeScript is enforced by `npm run lint`. Skipping Next's duplicate check
  // avoids an npm 12 stdout-format incompatibility when Next parses
  // `tsc --showConfig`; the standalone compiler remains the source of truth.
  typescript: {
    ignoreBuildErrors: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
