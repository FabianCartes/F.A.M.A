import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.FAMA_NEXT_DIST_DIR || ".next",
  experimental: {
    // Whole multipart request; the file itself is limited to 100 MiB.
    proxyClientMaxBodySize: 110 * 1024 * 1024,
    // All external HTTP rewrites, not just inference; leave backend time to return 504.
    proxyTimeout: 300000,
  },

  async rewrites() {
    const backendUrl = process.env.API_URL || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
