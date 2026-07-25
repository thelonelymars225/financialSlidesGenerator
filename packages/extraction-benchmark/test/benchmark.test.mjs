import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { criticalValueChecks, numericFidelity, readingOrderAccuracy } from "../src/metrics.mjs";
import { deterministicProvider, liveProviderFromEnvironment } from "../src/providers.mjs";
import { readJson, runBenchmark } from "../src/runner.mjs";

const manifestUrl = new URL("../fixtures/manifest.json", import.meta.url);

test("deterministic regression covers every safe fixture without secrets", async () => {
  const report = await runBenchmark({
    manifestUrl,
    provider: deterministicProvider(manifestUrl),
  });

  assert.deepEqual(report.summary, { total: 6, passed: 6, failed: 0 });
  assert.deepEqual(new Set(report.cases.map((item) => item.kind)), new Set([
    "born_digital_text",
    "financial_table",
    "scanned_page",
    "mixed_pdf",
    "chart",
  ]));
  assert.ok(report.cases.some((item) => item.route === "recorded_document_api"));
  for (const item of report.cases) {
    assert.equal(item.metrics.structuredOutputSuccess, true);
    assert.equal(item.metrics.estimatedCostUsd, 0);
    assert.ok(Object.values(item.metrics.criticalValueChecks).every(Boolean));
  }
});

test("negative signs, percentages, units, periods, and totals are exact regression checks", async () => {
  const expected = await readJson(
    new URL("../fixtures/expected/extracted-document-mixed-v0.1.json", import.meta.url),
  );
  const observed = structuredClone(expected);
  const margin = observed.pages[0].blocks[0].numericValues[1];
  observed.pages[0].blocks[0].text = observed.pages[0].blocks[0].text.replace("-2.5%", "2.5%");
  margin.displayedValue = "2.5%";
  margin.value = 0.025;

  assert.ok(numericFidelity(expected, observed) < 1);
  const checks = criticalValueChecks(observed, [
    {
      id: "negative-percentage",
      displayedValue: "-2.5%",
      value: -0.025,
      unit: "percent",
      period: "Q2 2026",
    },
  ]);
  assert.equal(checks["negative-percentage"], false);
});

test("reading-order regression detects reordered blocks", async () => {
  const expected = await readJson(
    new URL("../../contracts/examples/extracted-document-table-v0.1.json", import.meta.url),
  );
  const observed = structuredClone(expected);
  observed.pages[0].blocks.push({
    ...structuredClone(observed.pages[0].blocks[0]),
    id: "table-2",
    order: 1,
  });

  assert.ok(readingOrderAccuracy(expected, observed) < 1);
});

test("all source descriptors are explicitly synthetic", async () => {
  const manifest = await readJson(manifestUrl);
  for (const fixture of manifest.cases) {
    const source = JSON.parse(
      await readFile(new URL(fixture.source, manifestUrl), "utf8"),
    );
    assert.equal(source.synthetic, true);
  }
});

test("live mode is gated and never runs accidentally in CI", async () => {
  const originalAllow = process.env.EXTRACTION_BENCHMARK_ALLOW_LIVE;
  delete process.env.EXTRACTION_BENCHMARK_ALLOW_LIVE;
  await assert.rejects(liveProviderFromEnvironment(), /requires EXTRACTION_BENCHMARK_ALLOW_LIVE=1/);
  if (originalAllow === undefined) delete process.env.EXTRACTION_BENCHMARK_ALLOW_LIVE;
  else process.env.EXTRACTION_BENCHMARK_ALLOW_LIVE = originalAllow;
});
