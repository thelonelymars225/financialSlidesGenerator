import { readFile } from "node:fs/promises";
import { validateContract } from "@financial-slides/contracts/scripts/contract-validation.mjs";
import {
  criticalValueChecks,
  numericFidelity,
  readingOrderAccuracy,
  sourceLocationAccuracy,
  tableCellAccuracy,
  textAccuracy,
} from "./metrics.mjs";

export async function readJson(url) {
  return JSON.parse(await readFile(url, "utf8"));
}

function round(value) {
  return Number(value.toFixed(6));
}

function casePassed(metrics, thresholds) {
  return metrics.structuredOutputSuccess
    && metrics.textAccuracy >= thresholds.textAccuracy
    && metrics.tableCellAccuracy >= thresholds.tableCellAccuracy
    && metrics.numericFidelity >= thresholds.numericFidelity
    && metrics.readingOrderAccuracy >= thresholds.readingOrderAccuracy
    && metrics.sourceLocationAccuracy >= thresholds.sourceLocationAccuracy
    && metrics.latencyMs <= thresholds.maxLatencyMs
    && metrics.estimatedCostUsd <= thresholds.maxEstimatedCostUsd
    && Object.values(metrics.criticalValueChecks).every(Boolean);
}

export async function runBenchmark({
  manifestUrl = new URL("../fixtures/manifest.json", import.meta.url),
  provider,
}) {
  const manifest = await readJson(manifestUrl);
  const cases = [];

  for (const fixture of manifest.cases) {
    const expected = await readJson(new URL(fixture.expectedOutput, manifestUrl));
    const source = await readJson(new URL(fixture.source, manifestUrl));
    const observed = await provider.run(fixture, source);
    const validation = await validateContract("extractedDocument", observed.document);
    const metrics = {
      textAccuracy: round(textAccuracy(expected, observed.document)),
      tableCellAccuracy: round(tableCellAccuracy(expected, observed.document)),
      numericFidelity: round(numericFidelity(expected, observed.document)),
      readingOrderAccuracy: round(readingOrderAccuracy(expected, observed.document)),
      sourceLocationAccuracy: round(sourceLocationAccuracy(expected, observed.document)),
      latencyMs: observed.durationMs,
      structuredOutputSuccess: validation.valid,
      estimatedCostUsd: observed.estimatedCostUsd,
      criticalValueChecks: criticalValueChecks(observed.document, fixture.criticalValues),
    };
    cases.push({
      id: fixture.id,
      kind: fixture.kind,
      route: observed.route,
      passed: casePassed(metrics, manifest.thresholds),
      metrics,
      validationErrors: validation.errors,
    });
  }

  return {
    schemaVersion: "0.1",
    suite: "financial-slides-extraction",
    mode: provider.name,
    thresholds: manifest.thresholds,
    summary: {
      total: cases.length,
      passed: cases.filter((item) => item.passed).length,
      failed: cases.filter((item) => !item.passed).length,
    },
    cases,
  };
}
