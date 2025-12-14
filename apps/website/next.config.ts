import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    output: "export",
    distDir: process.env.distDir ?? "dist", // export to root of repo docs folder
    basePath: process.env.prefix ?? "",
    env: {
        // make it available to browser code
        NEXT_PUBLIC_BASE_PATH: process.env.prefix ?? "",
    },
    assetPrefix: (process.env.prefix ?? "") + "/",
    images: { unoptimized: true },
};

export default nextConfig;
