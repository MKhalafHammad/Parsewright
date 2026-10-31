import { expect, test, type Page } from "@playwright/test";

import { DIFF_MARKERS, LEDGER, mockRun, run, XSS } from "./fixtures";

function watchDialogs(page: Page): string[] {
  const dialogs: string[] = [];
  page.on("dialog", (d) => {
    dialogs.push(d.message());
    void d.dismiss();
  });
  return dialogs;
}

async function nothingInjected(page: Page, dialogs: string[]) {
  expect(dialogs).toEqual([]);
  expect(await page.locator("main script, main img, dialog script, dialog img").count()).toBe(0);
}

test("log text with script tags renders as plain text everywhere", async ({ page }) => {
  const dialogs = watchDialogs(page);
  await mockRun(page, run("awaiting_approval"), LEDGER);
  await page.goto("/runs/e2e00001");

  // Raw vs parsed: the highlighted value is the literal text, inside a <mark>, and the parsed
  // row shows it too.
  await expect(page.locator("mark", { hasText: "<script>alert(1)</script>" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Parsed fields" })).toContainText(XSS);
  // The activity feed: a guardrail block reason carries the string.
  await expect(page.getByLabel("Run activity")).toContainText(`blocked the proposal: EVAL-action reads ${XSS}`);
  // The tested configuration: a comment row.
  await expect(page.getByRole("region", { name: "default/props.conf" })).toContainText(XSS);

  // Phase view: the failing example, the evidence and the rationale.
  await page.goto("/runs/e2e00001?phase=extraction&attempt=1");
  await expect(page.getByRole("main")).toContainText(`msg=${XSS}`);
  await page.getByText("What the agent sees next").click();
  await expect(page.getByRole("main")).toContainText(`msg is missing: ${XSS}`);
  await page.goto("/runs/e2e00001?phase=extraction&attempt=2");
  await expect(page.getByRole("main")).toContainText(`KV_MODE misses ${XSS}`);
  // Technical detail: the verbatim JSON.
  await page.getByRole("main").getByText("Technical detail").first().click();

  await nothingInjected(page, dialogs);
});

test("the board and profile review render log-derived text as text", async ({ page }) => {
  const dialogs = watchDialogs(page);
  await page.route("**/api/engine/runs", (r) => r.fulfill({ json: [{ ...run("profile_review"), source_key: XSS }] }));
  await page.route("**/api/engine/runs/e2e00001/events*", (r) => r.fulfill({ json: [] }));
  await page.goto("/");
  await expect(page.getByRole("table", { name: "Jobs" })).toContainText("<script>alert(1)</script>");
  await expect(page.getByRole("region", { name: "Needs you" })).toContainText(XSS);

  const body = run("profile_review");
  await mockRun(page, {
    ...body,
    profile: { ...body.profile, timestamp_example: XSS, event_categories: [XSS], fields: [{ name: XSS, coverage: 1 }] },
  });
  await page.goto("/runs/e2e00001");
  await expect(page.getByRole("heading", { name: "Profile review" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Profile review" })).toContainText(XSS);
  await expect(page.getByRole("meter", { name: XSS })).toBeVisible();
  await nothingInjected(page, dialogs);
});

test("a parser update's diff, overrides and old event render as text, with no diff markers", async ({ page }) => {
  const dialogs = watchDialogs(page);
  const base = run("awaiting_approval");
  const oldRaw = `ts=1792483219000 action=accept src=${XSS}`;
  const update = {
    app: "TA-parsewright-acme-fw",
    version_from: "1.0.0",
    version_to: "1.1.0",
    patched: ["cim"],
    // The unified diff stays in the record for the CLI; the UI must never show it.
    diff: { "default/props.conf": `--- production/default/props.conf\n+++ update/default/props.conf\n@@ -1 +1 @@\n+EVAL-src = coalesce(src, "${XSS}")` },
    changes: [
      { file: "props.conf", stanza: "acme:fw", key: "EVAL-src", before: null, after: `coalesce(src, "${XSS}")`, change: "added" },
      { file: "props.conf", stanza: "acme:fw", key: "TIME_FORMAT", before: "%s%3N", after: "%Y-%m-%dT%H:%M:%S", change: "changed" },
      { file: "props.conf", stanza: "acme:fw", key: "EXTRACT-old", before: "x=(?<x>\\d+)", after: null, change: "removed" },
      { file: "props.conf", stanza: "acme:fw", key: "KV_MODE", before: "none", after: "none", change: "unchanged" },
      { file: "app.conf", stanza: "launcher", key: "version", before: "1.0.0", after: "1.1.0", change: "changed" },
    ],
    overrides: [`TIME_FORMAT: Splunk applies '${XSS}' from local/ or another app`],
    notes: ["Search-time changes apply to events already indexed as soon as it is promoted."],
    old_event: { time: 1792483219, raw: oldRaw, fields: {}, highlights: [] },
    rollback: "parsewright rollback TA-parsewright-acme-fw 1.0.0",
  };
  const body = { ...base, form: { update_of: "TA-parsewright-acme-fw" }, record: { ...base.record, report: { ...base.record.report, update } } };
  await mockRun(page, body);
  await page.goto("/runs/e2e00001");

  await expect(page.getByRole("heading", { name: /Parser update: .* 1\.0\.0 → 1\.1\.0/ })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Overrides that would hide this fix" })).toContainText(XSS);
  const diff = page.getByRole("region", { name: "Changes against production" });
  await expect(diff).toContainText("2 settings changed, 1 added, 1 removed");
  await expect(diff).toContainText(`coalesce(src, "${XSS}")`);
  await expect(diff).toContainText("1 unchanged setting");
  // Meaning never by colour alone: each changed row carries a word for screen readers.
  await expect(diff.locator(".sr-only", { hasText: "Added" })).toHaveCount(1);
  await expect(diff.locator(".sr-only", { hasText: "Removed" })).toHaveCount(1);
  await expect(diff.locator(".sr-only", { hasText: "Changed, before" })).toHaveCount(2);
  await expect(page.getByText(oldRaw)).toBeVisible();

  await page.getByRole("button", { name: "Approve…" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("in place with 1.1.0 (local/ is kept)");
  await nothingInjected(page, dialogs);
});

test("no diff view anywhere shows unified-diff markers", async ({ page }) => {
  await mockRun(page, run("awaiting_approval"), LEDGER);
  for (const url of ["/runs/e2e00001?phase=extraction&attempt=2", "/runs/e2e00001?phase=cim&attempt=2"]) {
    await page.goto(url);
    await expect(page.getByRole("heading", { name: /^Attempt 2/ })).toBeVisible();
    for (const d of await page.getByTestId("settings-diff").all()) {
      expect(await d.innerText(), url).not.toMatch(DIFF_MARKERS);
    }
  }
  // The full page text never shows a unified-diff header either.
  expect(await page.locator("main").innerText()).not.toMatch(/---|\+\+\+|@@/);
});
