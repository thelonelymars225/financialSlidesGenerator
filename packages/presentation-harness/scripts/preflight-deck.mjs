import { chromium } from "playwright";

import { runBrowserPreflight } from "../src/index.js";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const deckSpec = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const report = await runBrowserPreflight(deckSpec, { page });
  process.stdout.write(JSON.stringify(report));
  if (report.status !== "passed") process.exitCode = 1;
} finally {
  await browser.close();
}
