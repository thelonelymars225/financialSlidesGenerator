import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDeckHtml, layoutRegistry } from "../src/index.js";

async function fixture() {
  return JSON.parse(
    await readFile(
      new URL("../../contracts/examples/slide-spec-v0.1.json", import.meta.url),
      "utf8",
    ),
  );
}

test("registry constrains canvas, regions, typography, and components", () => {
  assert.deepEqual(layoutRegistry.chart.canvas, { width: 1280, height: 720 });
  assert.equal(layoutRegistry.chart.typography.titleSize, 44);
  assert.deepEqual(layoutRegistry["financial-table"].allowedComponents, ["text", "table"]);
  assert.deepEqual(layoutRegistry.chart.regions.primary, {
    x: 72,
    y: 144,
    width: 744,
    height: 504,
  });
});

test("compiles the complete fixture deck deterministically", async () => {
  const deck = await fixture();
  const first = compileDeckHtml(deck);
  const second = compileDeckHtml(structuredClone(deck));

  assert.equal(first, second);
  assert.equal((first.match(/<section class="slide /g) ?? []).length, 4);
  assert.match(first, /data-deck-id="deck-q2-2026"/);
  assert.match(first, /Revenue increased 24% quarter over quarter/);
  assert.match(first, /<table class="chart-data" data-chart-type="bar">/);
  assert.match(first, /Q2 2026/);
  assert.doesNotMatch(first, /<script|javascript:/i);
});

test("escapes plain content and rejects unsafe markup", async () => {
  const escaped = await fixture();
  escaped.title = "Revenue & margin";
  escaped.slides[0].title = `Revenue "improved"`;
  const html = compileDeckHtml(escaped);
  assert.match(html, /Revenue &amp; margin/);
  assert.match(html, /Revenue &quot;improved&quot;/);

  const unsafe = await fixture();
  unsafe.slides[0].components[0].text = "<script>alert(1)</script>";
  assert.throws(() => compileDeckHtml(unsafe), /unsafe content/);
});

test("fails closed for unknown layouts, components, and regions", async () => {
  const unknownLayout = await fixture();
  unknownLayout.slides[0].layoutId = "generated";
  assert.throws(() => compileDeckHtml(unknownLayout), /Unknown layout/);

  const component = await fixture();
  component.slides[0].components[0].type = "video";
  assert.throws(() => compileDeckHtml(component), /does not allow video/);

  const region = await fixture();
  region.slides[2].components[0].region = "right";
  assert.throws(() => compileDeckHtml(region), /does not define region right/);
});

test("resolves controlled image assets and rejects remote URLs", async () => {
  const deck = await fixture();
  deck.slides = [
    {
      id: "slide-image",
      order: 1,
      layoutId: "title",
      title: "Controlled image",
      components: [
        {
          id: "image",
          type: "image",
          region: "body",
          sources: [],
          assetRef: "asset:logo",
          altText: "Company logo",
        },
      ],
    },
  ];

  const html = compileDeckHtml(deck, { assets: { "asset:logo": "/assets/logo.png" } });
  assert.match(html, /src="\/assets\/logo.png"/);
  assert.throws(
    () =>
      compileDeckHtml(deck, {
        assets: { "asset:logo": "https://example.com/logo.png" },
      }),
    /Unsafe image asset URL/,
  );
});
