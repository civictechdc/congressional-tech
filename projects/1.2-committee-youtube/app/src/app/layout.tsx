import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

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
            <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
                {children}
            </body>
        </html>
    );
}
