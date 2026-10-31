import { expect, test } from "@playwright/test";

import { LEDGER, mockRun, run } from "./fixtures";

test("keyboard-only: upload, confirm the profile, approve", async ({ page }) => {
  const posts: { url: string; csrf: string | null }[] = [];
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/uploads", (r) => {
    posts.push({ url: r.request().url(), csrf: r.request().headers()["x-parsewright"] ?? null });
    return r.fulfill({ status: 201, json: { job: "e2e00001", duplicate: false, events: 300, estimated_tokens: 50000 } });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "New run" }).click();
  // A file chooser cannot be driven by keys in a headless browser; the file is attached, then
  // everything else is reached with Tab in document order.
  await page.getByLabel("Log file").setInputFiles({ name: "a.log", mimeType: "text/plain", buffer: Buffer.from("x\n".repeat(60)) });
  await page.getByLabel("Log file").focus();
  await page.keyboard.press("Tab"); // manifest
  await page.keyboard.press("Tab"); // update an existing TA (no: a new build)
  await expect(page.getByLabel("Update an existing TA (new log format)")).toBeFocused();
  await page.keyboard.press("Tab"); // vendor
  await expect(page.getByLabel("Vendor")).toBeFocused();
  await page.keyboard.type("acme");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Product")).toBeFocused();
  await page.keyboard.type("vpn");
  await page.keyboard.press("Tab"); // timezone
  await page.keyboard.press("Tab"); // skip profile review
  await page.keyboard.press("Tab"); // Start run
  await expect(page.getByRole("button", { name: "Start run" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status")).toContainText("Job e2e00001 queued");

  // Profile review, by keyboard.
  let state = "profile_review";
  await page.route("**/api/engine/runs/e2e00001/profile", (r) => {
    posts.push({ url: r.request().url(), csrf: r.request().headers()["x-parsewright"] ?? null });
    state = "awaiting_approval";
    return r.fulfill({ json: { job: "e2e00001", status: "queued" } });
  });
  await page.route("**/api/engine/runs/e2e00001/approve", (r) => {
    posts.push({ url: r.request().url(), csrf: r.request().headers()["x-parsewright"] ?? null });
    expect(JSON.parse(r.request().postData() ?? "{}")).toEqual({ sha256: "a".repeat(64) });
    state = "approved";
    return r.fulfill({ json: { job: "e2e00001", result: "approved" } });
  });
  await mockRun(page, {});
  await page.unroute("**/api/engine/runs/e2e00001");
  await page.route("**/api/engine/runs/e2e00001", (r) => r.fulfill({ json: run(state) }));
  await page.goto("/runs/e2e00001");

  await page.getByLabel("Timezone").focus();
  await page.keyboard.type("UTC");
  await page.getByRole("button", { name: "Confirm profile" }).focus();
  await page.keyboard.press("Enter");

  // Approval, with its second confirmation, by keyboard.
  await page.getByRole("button", { name: "Approve…" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alertdialog")).toContainText("Approve exactly this package");
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused(); // a reflexive Enter cancels
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter"); // "Yes, approve"
  await expect.poll(() => posts.map((p) => p.url.split("/").pop())).toEqual(["uploads", "profile", "approve"]);
  expect(posts.every((p) => p.csrf === "1")).toBe(true);
});

test("the live view shows a ledger event within 2 seconds", async ({ page }) => {
  await mockRun(page, run("running"), [
    { id: 7, at: "2026-10-28T10:00:01Z", event: "log", data: { line: "index-time attempt 1: sourcetype acme:vpn__test_e2e00001_a1", stage: "index-time", attempt: 1, visit: 1, actor: "index_time", kind: "start", detail: { max_attempts: 5 } } },
  ]);
  const started = Date.now();
  await page.goto("/runs/e2e00001");
  await expect(page.getByLabel("Run activity")).toContainText("started attempt 1 of 5", { timeout: 2000 });
  expect(Date.now() - started).toBeLessThan(5000);
  // The Now banner names the agent at work and what it is doing.
  await expect(page.getByRole("region", { name: "Now" })).toContainText("Index-time is writing attempt 1's settings");
});

test("phases and attempts are deep-linkable, with back and forward", async ({ page }) => {
  await mockRun(page, run("awaiting_approval"), LEDGER);
  await page.goto("/runs/e2e00001?phase=extraction&attempt=1");
  await expect(page.getByRole("heading", { name: /^Attempt 1/ })).toContainText("Failed");
  await expect(page.getByRole("main")).toContainText("Splunk checks: 1 of 1 failed");

  await page.getByRole("link", { name: /Attempt 2/ }).click();
  await expect(page).toHaveURL(/phase=extraction&attempt=2/);
  await expect(page.getByRole("heading", { name: /^Attempt 2/ })).toContainText("Passed");
  // Attempt 2 shows what changed since attempt 1, as rows.
  await expect(page.getByRole("region", { name: "Changes from the previous attempt" })).toContainText("1 setting changed, 1 added, 0 removed");

  await page.getByRole("navigation", { name: "Phases" }).getByRole("link", { name: /CIM mapping/ }).click();
  await expect(page).toHaveURL(/phase=cim/);
  await expect(page.getByRole("heading", { name: "CIM mapping", level: 2 })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/phase=extraction&attempt=2/);
  await page.goBack();
  await expect(page).toHaveURL(/phase=extraction&attempt=1/);
  await page.goForward();
  await expect(page.getByRole("heading", { name: /^Attempt 2/ })).toBeVisible();
});

test("arrow keys move along the phase rail", async ({ page }) => {
  await mockRun(page, run("awaiting_approval"), LEDGER);
  await page.goto("/runs/e2e00001");
  const rail = page.getByRole("navigation", { name: "Phases" });
  await rail.getByRole("link", { name: /^Profile Done/ }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(rail.getByRole("link", { name: /^Profile review/ })).toBeFocused();
  await page.keyboard.press("End");
  await expect(rail.getByRole("link", { name: /^Promoted/ })).toBeFocused();
  await page.keyboard.press("ArrowRight"); // wraps
  await expect(rail.getByRole("link", { name: /^Profile Done/ })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/phase=profile$/);
});

test("runs recorded before the event labels still show their agents, phases and attempts", async ({ page }) => {
  // The text lines the engine wrote before 2026-10-30, with no stage/actor/kind fields.
  const lines = [
    "job e2e00001: acme_vpn.json, 300 events in the manifest",
    "profile: json, acme/vpn, sourcetype acme:vpn, timestamp '2026-10-20T08:00:52+00:00', tz in timestamp: True, fields 5, CIM ['Authentication']",
    "profile review: auto-approved",
    "index-time attempt 1: sourcetype acme:vpn__test_e2e00001_a1",
    "  proposal: {'SHOULD_LINEMERGE': 'false', 'LINE_BREAKER': '([\\\\r\\\\n]+)', 'TIME_FORMAT': '%Y-%m-%dT%H:%M:%S%z'}",
    "  PASS event count: expected 300, actual 300",
    "  PASS timestamp accuracy: expected all _time = manifest, actual all match",
    "index-time: PASS (event count 300/300, attempt 1)",
    "extraction attempt 1",
    "  proposal: {'props': {'KV_MODE': 'none'}, 'transforms': {}}",
    "  FAIL field coverage: expected every profile field, actual user missing",
    "    user=alice action=login",
    "extraction attempt 2",
    "  proposal: {'props': {'KV_MODE': 'json'}, 'transforms': {}}",
    "  PASS field coverage: expected every profile field, actual all fields covered",
    "extraction: PASS (attempt 2)",
    "cim attempt 1: models Authentication",
    "  proposal: {'props': {'FIELDALIAS-user': 'user AS user'}, 'eventtypes': {}, 'tags': {}}",
    "  PASS Authentication: events in the data model: expected 300, actual 300",
    "cim: PASS (attempt 1)",
    "holdout: learned from 200 lines, passed on the full file (300 events)",
    "CIM Authentication: required fields 4/4 passed, available fields mapped 4/4, not in source 1 (app)",
    "awaiting approval: sha256 " + "a".repeat(64),
  ];
  await mockRun(page, run("awaiting_approval"), lines.map((line, i) => ({ id: i + 1, at: `2026-10-28T10:00:${String(i).padStart(2, "0")}Z`, event: "log", data: { line } })));
  await page.goto("/runs/e2e00001");

  const rail = page.getByRole("navigation", { name: "Phases" });
  for (const phase of ["Profile", "Index-time", "Extraction", "CIM mapping"]) {
    await expect(rail.getByRole("link", { name: new RegExp(`^${phase} Done`) })).toBeVisible();
  }
  await expect(rail.getByRole("link", { name: /^Extraction Done · 2 attempts/ })).toBeVisible();
  const feed = page.getByLabel("Run activity");
  await expect(feed).toContainText("Extraction (AI agent) proposed 1 setting");
  await expect(feed).toContainText("Profiler (AI agent) described the log");
  await expect(feed).toContainText("Splunk checks: 1 of 1 failed");

  await page.goto("/runs/e2e00001?phase=extraction&attempt=2");
  await expect(page.getByRole("region", { name: "Changes from the previous attempt" })).toContainText("1 setting changed, 0 added, 0 removed");
  await page.goto("/runs/e2e00001?phase=extraction&attempt=1");
  await expect(page.getByRole("main")).toContainText("user=alice action=login"); // the failing example
});
