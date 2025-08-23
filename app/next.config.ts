import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    output: "export",
    distDir: "../docs", // export to root of repo docs folder
};

export default nextConfig;
