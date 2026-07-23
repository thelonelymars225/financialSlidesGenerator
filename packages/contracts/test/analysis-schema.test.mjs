import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  calculateDerivedValue,
  expectedNormalizedValue,
} from "../scripts/financial-calculations.mjs";
import { validateContract } from "../scripts/contract-validation.mjs";

async function readExample(name) {
  return JSON.parse(await readFile(new URL(`../examples/${name}`, import.meta.url), "utf8"));
}

test("Analysis v0.1 remains valid for backward compatibility", async () => {
  const result = await validateContract("analysis", await readExample("analysis-v0.1.json"));
  assert.deepEqual(result, { valid: true, errors: [] });
});

test("Analysis v0.2 satisfies schema and semantic validation", async () => {
  const result = await validateContract("analysis", await readExample("analysis-v0.2.json"));
  assert.deepEqual(result, { valid: true, errors: [] });
});

test("rejects unsupported analysis versions", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.schemaVersion = "9.9";

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /unsupported analysis contract version/);
});

test("rejects ungrounded findings", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.findings[0].evidence = [];

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /must NOT have fewer than 1 items/);
});

test("rejects evidence from undeclared documents", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.findings[0].evidence[0].documentId = "document-unknown";

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /undeclared source document document-unknown/);
});

test("rejects unknown metric and finding references", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.findings[0].metricIds.push("metric-unknown");
  analysis.slideIntents[0].findingIds.push("finding-unknown");

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /unknown metric metric-unknown/);
  assert.match(result.errors.join("\n"), /unknown finding finding-unknown/);
});

test("rejects duplicate identities and invalid periods", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.metrics[1].id = analysis.metrics[0].id;
  analysis.metrics[0].period.startDate = "2026-02-31";
  analysis.metrics[0].period.endDate = "2026-01-01";

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /duplicate metric id/);
  assert.match(result.errors.join("\n"), /invalid startDate/);
  assert.match(result.errors.join("\n"), /period starts after it ends/);
});

test("checks normalized values and derived calculations", async () => {
  const invalidNormalization = await readExample("analysis-v0.2.json");
  invalidNormalization.metrics[0].normalizedValue = 10;

  const normalizationResult = await validateContract("analysis", invalidNormalization);
  assert.equal(normalizationResult.valid, false);
  assert.match(normalizationResult.errors.join("\n"), /value × scaleFactor/);

  const invalidCalculation = await readExample("analysis-v0.2.json");
  invalidCalculation.metrics[2].normalizedValue = 0.5;

  const calculationResult = await validateContract("analysis", invalidCalculation);
  assert.equal(calculationResult.valid, false);
  assert.match(calculationResult.errors.join("\n"), /calculation result must equal 0.24/);
});

test("rejects derived calculations with incompatible units", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.metrics[1].unit.code = "EUR";

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /calculation operands must use compatible units/);
});

test("unit normalization and percentage change are deterministic", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  const metricsById = new Map(analysis.metrics.map((metric) => [metric.id, metric]));

  assert.equal(expectedNormalizedValue(analysis.metrics[0]), 10000000);
  assert.equal(calculateDerivedValue(analysis.metrics[2], metricsById), 0.24);
});

test("requires slide intents to reference grounded analysis", async () => {
  const analysis = await readExample("analysis-v0.2.json");
  analysis.slideIntents[0].findingIds = [];
  analysis.slideIntents[0].metricIds = [];

  const result = await validateContract("analysis", analysis);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /must reference at least one finding or metric/);
});
