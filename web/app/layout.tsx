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
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2">
          Skip to content
        </a>
        <header className="border-b border-slate-200 bg-white">
          <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
            <Link href="/" className="font-semibold">
              Parsewright
            </Link>
            <span className="text-sm text-slate-500">Agents propose, code acts, Splunk judges.</span>
          </nav>
        </header>
        <main id="main" className="mx-auto max-w-6xl px-4 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
