import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import { headers } from "next/headers";

import "./globals.css";

const heroosSans = Plus_Jakarta_Sans({
  variable: "--font-heroos-sans",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "HeroOS",
  description: "Your HR Department without an HR Department. Temporary demonstration environment (synthetic data only).",
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
      className={`${heroosSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
