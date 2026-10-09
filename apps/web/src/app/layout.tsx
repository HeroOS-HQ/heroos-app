import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "HeroOS",
  description: "HeroOS temporary demonstration environment (synthetic data only).",
  robots: { index: false, follow: false },
};

// Nonce-based CSP (src/proxy.ts) needs every page rendered per request: a
// prerendered static shell could not carry the nonce. Reading the request
// headers here makes the whole app dynamic; `instant = false` allows that.
export const instant = false;

export default async function RootLayout({ children }: LayoutProps<"/">) {
  await headers();
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
