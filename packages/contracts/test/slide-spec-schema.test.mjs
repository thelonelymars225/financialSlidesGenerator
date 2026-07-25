import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { validateContract } from "../scripts/contract-validation.mjs";

async function slideSpec() {
  return JSON.parse(
    await readFile(new URL("../examples/slide-spec-v0.1.json", import.meta.url), "utf8"),
  );
}

test("slide specification v0.1 covers the representative deck", async () => {
  const result = await validateContract("slideSpec", await slideSpec());
  assert.deepEqual(result, { valid: true, errors: [] });
});

test("rejects arbitrary markup, URLs, layouts, components, and assets", async () => {
  const markup = await slideSpec();
  markup.slides[0].components[0].text = "<script>alert('x')</script>";

  const unsupported = await slideSpec();
  unsupported.slides[0].layoutId = "model-generated-layout";

  const unsafeAsset = await slideSpec();
  unsafeAsset.slides[0].components.push({
    id: "remote-image",
    type: "image",
    region: "background",
    sources: [],
    assetRef: "https://example.com/image.png",
    altText: "Remote image",
  });

  for (const [value, pattern] of [
    [markup, /unsafe markup/],
    [unsupported, /must be equal to one of the allowed values/],
    [unsafeAsset, /must match pattern/],
  ]) {
    const result = await validateContract("slideSpec", value);
    assert.equal(result.valid, false);
    assert.match(result.errors.join("\n"), pattern);
  }
});

test("rejects undeclared sources and duplicate or non-contiguous identities", async () => {
  const deck = await slideSpec();
  deck.slides[1].id = deck.slides[0].id;
  deck.slides[1].order = 4;
  deck.slides[1].components[0].id = deck.slides[0].components[0].id;
  deck.slides[1].components[0].sources[0].documentId = "document-unknown";

  const result = await validateContract("slideSpec", deck);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /duplicate slide id/);
  assert.match(result.errors.join("\n"), /duplicate slide order/);
  assert.match(result.errors.join("\n"), /duplicate component id/);
  assert.match(result.errors.join("\n"), /undeclared document/);
  assert.match(result.errors.join("\n"), /contiguous/);
});

test("rejects invalid layout contents and mismatched table or chart shapes", async () => {
  const deck = await slideSpec();
  deck.slides[0].components[0].type = "chart";
  deck.slides[2].components[0].rows[0].pop();
  deck.slides[3].components[0].series[0].values.pop();

  const result = await validateContract("slideSpec", deck);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /must have required property 'chartType'/);

  const shapedDeck = await slideSpec();
  shapedDeck.slides[2].components[0].rows[0].pop();
  shapedDeck.slides[3].components[0].series[0].values.pop();
  const shapedResult = await validateContract("slideSpec", shapedDeck);
  assert.equal(shapedResult.valid, false);
  assert.match(shapedResult.errors.join("\n"), /row 0 must match its column count/);
  assert.match(shapedResult.errors.join("\n"), /must match its categories/);
});

test("rejects changed signs, units, periods, and normalized values", async () => {
  const invalidUnit = await slideSpec();
  invalidUnit.slides[1].components[0].value.unit.code = "usd";
  const unitResult = await validateContract("slideSpec", invalidUnit);
  assert.equal(unitResult.valid, false);
  assert.match(unitResult.errors.join("\n"), /must match pattern/);

  const invalidValue = await slideSpec();
  const value = invalidValue.slides[1].components[0].value;
  value.normalizedValue = -value.normalizedValue;
  value.period.startDate = "2026-06-31";

  const result = await validateContract("slideSpec", invalidValue);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /normalizedValue must equal/);
  assert.match(result.errors.join("\n"), /invalid startDate/);
});

test("enforces deck, component, text, table, chart, and asset limits", async () => {
  const deck = await slideSpec();
  deck.slides = Array.from({ length: 41 }, (_, index) => ({
    ...structuredClone(deck.slides[0]),
    id: `slide-${index + 1}`,
    order: index + 1,
  }));

  const result = await validateContract("slideSpec", deck);
  assert.equal(result.valid, false);
  assert.match(result.errors.join("\n"), /must NOT have more than 40 items/);
});
