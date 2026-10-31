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
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-md focus:bg-surface focus:p-2">
          Skip to content
        </a>
        <header className="border-b border-line bg-surface">
          <nav aria-label="Main" className="mx-auto flex max-w-[90rem] flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 sm:px-6">
            <Link href="/" className="text-base font-semibold">
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
