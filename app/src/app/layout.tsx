import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { NavBar } from "@/components/navigation-bar";
import Link from "next/link";
import favicon from "@/../public/favicon.ico";
import Image from "next/image";
import { ReactQueryProvider } from "./providers";

// Fonts (server-safe; no client runtime needed)
const geistSans = Geist({
    variable: "--font-geist-sans",
    subsets: ["latin"],
});
const geistMono = Geist_Mono({
    variable: "--font-geist-mono",
    subsets: ["latin"],
});

// Force static rendering for the whole subtree (SSG-friendly)
export const dynamic = "force-static";

// App-level metadata (works with static export)
export const metadata: Metadata = {
    title: "Congressional YouTube",
    description: "Simple static app exploring congressional committee YouTube content.",
};

export default function RootLayout({
    children,
}: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="en" className="h-full">
            <body
                className={`flex h-full flex-col ${geistSans.variable} ${geistMono.variable} antialiased`}
            >
                <ReactQueryProvider>
                    {/* Top Navigation */}
                    <div className="z-10 flex flex-row items-center p-2 shrink-0">
                        <Link href="/">
                            <Image
                                src={favicon}
                                alt="Favicon"
                                className="h-8 w-auto cursor-pointer"
                            />
                        </Link>
                        <NavBar />
                    </div>

                    {/* Main Content (scrollable, resizes naturally) */}
                    <main className="flex-1 overflow-y-auto p-2">
                        {children}
                    </main>
                </ReactQueryProvider>
            </body>
        </html>
    );
}
