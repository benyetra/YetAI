import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async redirects() {
    return [
      {
        source: "/live-betting",
        destination: "/bets",
        permanent: true,
      },
      {
        source: "/live-betting/:path*",
        destination: "/bets",
        permanent: true,
      },
    ];
  },
  // Temporarily disable TypeScript and ESLint checking during build
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Fix workspace root detection for CI/CD environments
  outputFileTracingRoot: process.env.NODE_ENV === 'production' && process.env.CI ? process.cwd() : undefined,
};

export default nextConfig;
