import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";

import "./globals.css";

export const metadata: Metadata = {
  title: "Parsewright",
  description: "Raw sample logs in, a tested CIM-compliant Splunk add-on out.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  await connection(); // render per request, so Next.js can attach this request's CSP nonce
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-md focus:bg-surface-solid focus:p-2">
          Skip to content
        </a>
        <header className="glass-strong sticky top-0 z-30 border-x-0 border-t-0">
          <nav aria-label="Main" className="mx-auto flex max-w-[90rem] flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
            <Link href="/" className="bg-gradient-to-r from-[#c4b5fd] via-[#7dd3fc] to-[#f0abfc] bg-clip-text text-lg font-bold tracking-tight text-transparent">
              Parsewright
            </Link>
            <Link href="/" className="text-sm text-muted hover:text-fg">
              Runs
            </Link>
            <Link href="/tas" className="text-sm text-muted hover:text-fg">
              TA registry
            </Link>
            <span className="ml-auto hidden text-[13px] text-subtle md:inline">
              Agents propose · code acts · Splunk judges · you approve
            </span>
          </nav>
        </header>
        <main id="main" className="mx-auto max-w-[90rem] px-4 py-6 sm:px-6">
          {children}
        </main>
      </body>
    </html>
  );
}
