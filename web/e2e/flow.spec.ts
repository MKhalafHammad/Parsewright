import { expect, test } from "@playwright/test";

import { mockRun, run } from "./fixtures";

test("keyboard-only: upload, confirm the profile, approve", async ({ page }) => {
  const posts: { url: string; csrf: string | null }[] = [];
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/tas", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/engine/uploads", (r) => {
    posts.push({ url: r.request().url(), csrf: r.request().headers()["x-parsewright"] ?? null });
    return r.fulfill({ status: 201, json: { job: "e2e00001", duplicate: false, events: 300, estimated_tokens: 50000 } });
  });

  await page.goto("/");
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
  await page.keyboard.press("Enter"); // "Yes, approve" has focus
  await expect.poll(() => posts.map((p) => p.url.split("/").pop())).toEqual(["uploads", "profile", "approve"]);
  expect(posts.every((p) => p.csrf === "1")).toBe(true);
});

test("the live view shows a ledger event within 2 seconds", async ({ page }) => {
  await mockRun(page, run("running"), [
    { id: 7, at: "2026-10-28T10:00:01Z", event: "log", data: { line: "index-time attempt 1: sourcetype acme:vpn__test_e2e00001_a1" } },
  ]);
  const started = Date.now();
  await page.goto("/runs/e2e00001");
  await expect(page.getByLabel("Run timeline")).toContainText("index-time attempt 1", { timeout: 2000 });
  expect(Date.now() - started).toBeLessThan(5000);
});
