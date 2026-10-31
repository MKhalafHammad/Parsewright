import { expect, test } from "@playwright/test";

// The real Next.js server and proxy (no mocks): refusals happen before anything reaches the
// engine. ENGINE_URL points at a closed port, so a request that IS forwarded gets 502.
const SAME = { Origin: "http://localhost:3100", "X-Parsewright": "1" };

test("DNS rebinding: an unknown Host is refused on pages and the API", async ({ request }) => {
  for (const path of ["/", "/runs/abcd1234", "/api/engine/runs", "/api/engine/admin/status"]) {
    const r = await request.get(path, { headers: { Host: "rebind.attacker.example:3100" } });
    expect(r.status(), path).toBe(421);
  }
  const post = await request.post("/api/engine/runs/abcd1234/approve", {
    headers: { ...SAME, Host: "rebind.attacker.example:3100", Origin: "http://rebind.attacker.example:3100" },
    data: { sha256: "a".repeat(64) },
  });
  expect(post.status()).toBe(421);
});

test("cross-site state changes are refused", async ({ request }) => {
  const data = { sha256: "a".repeat(64) };
  const noHeader = await request.post("/api/engine/runs/abcd1234/approve", { headers: { Origin: SAME.Origin }, data });
  expect(noHeader.status()).toBe(403);
  const foreign = await request.post("/api/engine/runs/abcd1234/approve", {
    headers: { ...SAME, Origin: "https://evil.example.com" },
    data,
  });
  expect(foreign.status()).toBe(403);
  const noOrigin = await request.post("/api/engine/runs/abcd1234/approve", { headers: { "X-Parsewright": "1" }, data });
  expect(noOrigin.status()).toBe(403);
  // Positive control: the same request from the UI's own origin is forwarded (closed engine: 502).
  const ok = await request.post("/api/engine/runs/abcd1234/approve", { headers: SAME, data });
  expect(ok.status()).toBe(502);
});

test("only allowlisted engine paths are forwarded, however they are spelled", async ({ request }) => {
  const paths = ["admin%2F..%2Fruns", "runs/ABC", "docs", "runs/abcd1234/record", "openapi.json",
    "runs/abcd1234%2Fapprove", "runs%2Fabcd1234%2Fapprove", "RUNS/abcd1234/approve"];
  // ("runs//x/approve" is collapsed to "runs/x/approve" before any app code sees it: the same
  // allowlisted endpoint, so it is not tested as a bypass.)
  for (const path of paths) {
    expect((await request.get(`/api/engine/${path}`)).status(), `GET ${path}`).toBe(404);
    expect((await request.post(`/api/engine/${path}`, { headers: SAME })).status(), `POST ${path}`).toBe(404);
  }
  expect((await request.get("/api/engine/runs")).status()).toBe(502); // allowlisted: forwarded
});

test("pages and the API carry security headers, with a nonce instead of unsafe-inline", async ({ request }) => {
  const page = await request.get("/");
  const csp = page.headers()["content-security-policy"] ?? "";
  expect(csp).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
  expect(csp).not.toContain("script-src 'self' 'unsafe-inline'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(page.headers()["x-frame-options"]).toBe("DENY");
  expect(page.headers()["x-powered-by"]).toBeUndefined();
  const second = (await request.get("/")).headers()["content-security-policy"];
  expect(second).not.toBe(csp); // a fresh nonce per request
  const api = await request.get("/api/engine/runs");
  expect(api.headers()["x-content-type-options"]).toBe("nosniff");
});
