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
