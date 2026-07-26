import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { chromium } from "playwright";

import { runBrowserPreflight } from "../src/index.js";

test("approved financial deck passes browser layout preflight", async (context) => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    if (process.env.CI) throw error;
    context.skip("Chromium is installed by CI for the browser integration check.");
    return;
  }

  try {
    const deck = JSON.parse(
      await readFile(
        new URL("../../contracts/examples/slide-spec-v0.1.json", import.meta.url),
        "utf8",
      ),
    );
    const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
    const report = await runBrowserPreflight(deck, { page });

    assert.equal(report.status, "passed");
    assert.deepEqual(report.failures, []);
  } finally {
    await browser.close();
  }
});
