// Runs before every page and API request (Next.js 16 "proxy", formerly middleware).
// 1. Host allowlist: a DNS-rebinding page arrives with the attacker's host name and is refused
//    before anything renders or reaches the engine (threat T8.5).
// 2. A per-request CSP nonce, so scripts need no 'unsafe-inline' (Next.js attaches the nonce
//    to its own scripts).
import { NextResponse, type NextRequest } from "next/server";

import { allowedHost } from "@/lib/hosts";

export function proxy(req: NextRequest) {
  if (!allowedHost(req.headers.get("host"))) {
    return new NextResponse("unknown host", { status: 421 });
  }
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
  const headers = new Headers(req.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set("Content-Security-Policy", csp);
  return res;
}

export const config = {
  matcher: [{ source: "/((?!_next/static|_next/image|favicon.ico).*)" }],
};
