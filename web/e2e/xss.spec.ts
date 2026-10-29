import { expect, test } from "@playwright/test";

import { mockRun, run, XSS } from "./fixtures";

test("log text with script tags renders as plain text everywhere", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  await mockRun(page, run("awaiting_approval"), [
    { id: 1, at: "2026-10-28T10:00:01Z", event: "log", data: { line: `  FAIL event: ${XSS}` } },
  ]);
  await page.goto("/runs/e2e00001");

  // Raw vs parsed: the highlighted value is the literal text, inside a <mark>.
  await expect(page.locator("mark", { hasText: "<script>alert(1)</script>" })).toBeVisible();
  await expect(page.getByText(XSS).first()).toBeVisible();
  // The timeline line and the config text show it as text too.
  await expect(page.getByLabel("Run timeline")).toContainText("<script>alert(1)</script>");
  await page.getByText("default/props.conf").click();
  await expect(page.locator("pre")).toContainText(XSS);

  // Nothing executed and nothing was injected as markup.
  expect(dialogs).toEqual([]);
  expect(await page.locator("main script").count()).toBe(0);
  expect(await page.locator("main img").count()).toBe(0);
});


test("the board and profile review render log-derived text as text", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  await page.route("**/api/engine/runs", (r) =>
    r.fulfill({ json: [{ ...run("queued"), source_key: XSS }] }),
  );
  await page.goto("/");
  await expect(page.getByRole("table", { name: "Jobs" })).toContainText("<script>alert(1)</script>");

  const body = run("profile_review");
  await mockRun(page, {
    ...body,
    profile: { ...body.profile, timestamp_example: XSS, event_categories: [XSS], fields: [{ name: XSS, coverage: 1 }] },
  });
  await page.goto("/runs/e2e00001");
  await expect(page.getByRole("heading", { name: "Profile review" })).toBeVisible();
  await expect(page.locator("dl").first()).toContainText("<script>alert(1)</script>");
  expect(dialogs).toEqual([]);
  expect(await page.locator("main script, main img").count()).toBe(0);
});

test("a parser update's diff, overrides and old event render as text", async ({ page }) => {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  const base = run("awaiting_approval");
  const oldRaw = `ts=1792483219000 action=accept src=${XSS}`;
  const update = {
    app: "TA-parsewright-acme-fw",
    version_from: "1.0.0",
    version_to: "1.1.0",
    patched: ["cim"],
    diff: { "default/props.conf": `--- production/default/props.conf\n+++ update/default/props.conf\n+EVAL-src = coalesce(src, "${XSS}")` },
    overrides: [`TIME_FORMAT: Splunk applies '${XSS}' from local/ or another app`],
    notes: ["Search-time changes apply to events already indexed as soon as it is promoted."],
    old_event: { time: 1792483219, raw: oldRaw, fields: {}, highlights: [] },
    rollback: "parsewright rollback TA-parsewright-acme-fw 1.0.0",
  };
  const body = { ...base, record: { ...base.record, report: { ...base.record.report, update } } };
  await mockRun(page, body);
  await page.goto("/runs/e2e00001");

  await expect(page.getByRole("heading", { name: /Parser update: .* 1\.0\.0 → 1\.1\.0/ })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Overrides that would hide this fix" })).toContainText(XSS);
  await expect(page.getByText(`+EVAL-src = coalesce(src, "${XSS}")`)).toBeVisible();
  await expect(page.getByText(oldRaw)).toBeVisible();
  await page.getByRole("button", { name: "Approve…" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("in place with 1.1.0 (local/ is kept)");

  expect(dialogs).toEqual([]);
  expect(await page.locator("main script, main img").count()).toBe(0);
});
