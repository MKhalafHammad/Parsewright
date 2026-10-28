// Server-side only: which Host headers and Origins this UI answers to. Fixed lists, never
// derived from the request (a rebinding page controls its own Host and Origin).
const list = (v: string | undefined, fallback: string) =>
  (v ?? fallback).split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);

export const ALLOWED_HOSTS = list(process.env.ALLOWED_HOSTS, "localhost:3000,127.0.0.1:3000");
export const WEB_ORIGINS = list(process.env.WEB_ORIGINS, "http://localhost:3000,http://127.0.0.1:3000");

export const allowedHost = (host: string | null) => !!host && ALLOWED_HOSTS.includes(host.toLowerCase());
export const allowedOrigin = (origin: string | null) => !!origin && WEB_ORIGINS.includes(origin.toLowerCase());
