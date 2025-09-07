import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Temporarily disable TypeScript and ESLint checking during build
  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
};

export default nextConfig;
