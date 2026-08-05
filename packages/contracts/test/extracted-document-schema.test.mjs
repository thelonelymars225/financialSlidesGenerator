import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { validateContract } from "../scripts/contract-validation.mjs";

async function readExample(name) {
  return JSON.parse(await readFile(new URL(`../examples/${name}`, import.meta.url), "utf8"));
}

for (const exampleName of [
  "extracted-document-text-v0.1.json",
  "extracted-document-table-v0.1.json",
  "extracted-document-scan-v0.1.json",
  "extracted-document-chart-v0.1.json",
]) {
  test(`${exampleName} satisfies the extracted-document contract`, async () => {
    const result = await validateContract("extractedDocument", await readExample(exampleName));
    assert.deepEqual(result, { valid: true, errors: [] });
  });
}

test("finance-aware v0.2 satisfies the extracted-document contract", async () => {
  const result = await validateContract(
    "extractedDocument",
    await readExample("extracted-document-financial-v0.2.json"),
  );
  assert.deepEqual(result, { valid: true, errors: [] });
});

test("rejects unsupported extracted-document versions", async () => {
  const document = await readExample("extracted-document-financial-v0.2.json");
  document.schemaVersion = "0.3";

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /unsupported extractedDocument contract version/);
});

test("checks financial normalization and evidence lineage", async () => {
  const document = await readExample("extracted-document-financial-v0.2.json");
  document.financialFacts[0].normalizedValue = 18;
  document.financialFacts[0].evidence.blockId = "missing-block";

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /normalizedValue must equal parsedValue/);
  assert.match(result.errors.join("\n"), /references unknown block/);
});

test("requires ambiguity to be explicit and reviewable", async () => {
  const document = await readExample("extracted-document-financial-v0.2.json");
  const fact = document.financialFacts[0];
  fact.period = { type: "unknown", label: null, startDate: null, endDate: null };
  fact.confidence.period = 0;

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /must flag period.missing/);
});

test("rejects an incomplete block without provenance", async () => {
  const document = await readExample("extracted-document-text-v0.1.json");
  delete document.pages[0].blocks[0].source;

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /required property 'source'/);
});

test("rejects confidence values outside the supported range", async () => {
  const document = await readExample("extracted-document-scan-v0.1.json");
  document.pages[0].blocks[0].confidence = 1.1;

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /must be <= 1/);
});

test("requires the displayed value beside a parsed numeric value", async () => {
  const document = await readExample("extracted-document-table-v0.1.json");
  delete document.pages[0].blocks[0].cells[3].numericValue.displayedValue;

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /required property 'displayedValue'/);
});

test("rejects source geometry that exceeds page dimensions", async () => {
  const document = await readExample("extracted-document-chart-v0.1.json");
  document.pages[0].blocks[0].source.boundingBox.right = 700;

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /bounding box exceeds page dimensions/);
});

test("rejects table cells that exceed declared dimensions", async () => {
  const document = await readExample("extracted-document-table-v0.1.json");
  document.pages[0].blocks[0].cells[3].columnSpan = 2;

  const result = await validateContract("extractedDocument", document);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /exceeds columnCount/);
});
