import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep the browser focused on the analyst workbench; Next's dev overlay
  // can fail when its optional userspace bridge is unavailable.
  devIndicators: false,
};

export default nextConfig;
