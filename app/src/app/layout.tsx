import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { NavBar } from "@/components/navigation-bar";
import Link from "next/link";
import favicon from "@/../public/favicon.ico";
import Image from "next/image";

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
        <html lang="en">
            <body
                className={`flex flex-col ${geistSans.variable} ${geistMono.variable} antialiased`}
            >
                <div className="fixed z-10 flex max-h-min flex-row items-center p-2">
                    <Link href="/">
                        <Image src={favicon} alt="Favicon" className="h-8 w-auto cursor-pointer" />
                    </Link>
                    <NavBar />
                </div>
                <div className="pt-10">{children}</div>
            </body>
        </html>
    );
}
