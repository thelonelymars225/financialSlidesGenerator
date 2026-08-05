import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  compileDeckHtml,
  densityPreflightPolicy,
  defaultPresentationTheme,
  formatSourceReferences,
  layoutRegistry,
  resolvePresentationTheme,
} from "../src/index.js";
import { visualFixture } from "./visual-fixture.mjs";

function luminance(hex) {
  const channels = hex.match(/.{2}/g).map((value) => Number.parseInt(value, 16) / 255);
  const linear = channels.map((value) =>
    value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrast(left, right) {
  const [lighter, darker] = [luminance(left), luminance(right)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

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
  assert.deepEqual(layoutRegistry["key-drivers"].allowedComponents, ["text", "metric", "insight"]);
  assert.deepEqual(layoutRegistry["risks-actions"].allowedComponents, ["text", "insight"]);
  assert.deepEqual(layoutRegistry["sources-appendix"].allowedComponents, ["text", "table"]);
  assert.deepEqual(layoutRegistry.chart.regions.primary, {
    x: 72,
    y: 144,
    width: 744,
    height: 504,
  });
});

test("compiles every polished core layout deterministically across density profiles", () => {
  const snapshots = {
    concise: "b61a4279fe1fb05d1172ac346f1fb7d8167111e9f0b9f581e31b84abc4972821",
    balanced: "1d9830c13e9b164c7e870d1ebc6672a564d348e28eeb1abf2b82fe50bbe42067",
    detailed: "7977cf1fb2d723d77fe37b977672aa5733541c97735dc07ed31e1d35a7168864",
  };
  for (const density of ["concise", "balanced", "detailed"]) {
    const deck = visualFixture(density);
    const html = compileDeckHtml(deck);
    assert.equal(html, compileDeckHtml(structuredClone(deck)));
    assert.equal(createHash("sha256").update(html).digest("hex"), snapshots[density]);
    assert.equal((html.match(/<section class="slide /g) ?? []).length, 8);
    for (const layout of ["title", "executive-summary", "kpi-grid", "chart", "financial-table", "key-drivers", "risks-actions", "sources-appendix"]) {
      assert.match(html, new RegExp(`layout-${layout}`));
    }
    assert.match(html, /metric-negative/);
    assert.doesNotMatch(html, /<script|javascript:/i);
  }
});

test("keeps long citations in data while containing the visible source footer", () => {
  const slide = visualFixture("balanced").slides.at(-1);
  const visible = formatSourceReferences(slide);
  const complete = formatSourceReferences(slide, Number.POSITIVE_INFINITY);

  assert.ok(visible.length <= 180);
  assert.match(visible, /…$/);
  assert.ok(complete.length > visible.length);
  assert.match(complete, /p\.10/);
});

test("default theme is complete, immutable, and readable", () => {
  assert.equal(resolvePresentationTheme().id, "theme-corporate-default");
  assert.ok(Object.isFrozen(defaultPresentationTheme));
  assert.ok(Object.isFrozen(defaultPresentationTheme.colors));
  assert.match(defaultPresentationTheme.fonts.fallback, /Arial/);
  assert.equal(defaultPresentationTheme.chart.palette.length, 5);
  assert.ok(contrast(defaultPresentationTheme.colors.ink, defaultPresentationTheme.colors.canvas) >= 7);
  assert.ok(contrast(defaultPresentationTheme.colors.accent, defaultPresentationTheme.colors.canvas) >= 4.5);
  assert.throws(() => resolvePresentationTheme("generated-theme"), /Unknown presentation theme/);
});

test("compiles the complete fixture deck deterministically", async () => {
  const deck = await fixture();
  const first = compileDeckHtml(deck);
  const second = compileDeckHtml(structuredClone(deck));

  assert.equal(first, second);
  assert.equal((first.match(/<section class="slide /g) ?? []).length, 4);
  assert.match(first, /data-deck-id="deck-q2-2026"/);
  assert.match(first, /data-density-profile="balanced"/);
  assert.match(first, /Revenue increased 24% quarter over quarter/);
  assert.match(first, /<table class="chart-data" data-chart-type="bar">/);
  assert.match(first, /Q2 2026/);
  assert.match(first, /Sources: document-financial-report p\.1/);
  assert.match(first, /--color|#0f766e|#17324d/);
  assert.doesNotMatch(first, /<script|javascript:/i);
});

test("density constraints reach compilation and preflight", async () => {
  const deck = await fixture();
  assert.deepEqual(densityPreflightPolicy(deck), {
    minFontSize: 16,
    minSpacing: 4,
    maxAutoFitPasses: 2,
    maxRepairAttempts: 2,
  });

  const unknown = await fixture();
  unknown.densityProfile = "maximum";
  assert.throws(() => compileDeckHtml(unknown), /density contract/);

  const overLimit = await fixture();
  overLimit.densityConstraints.maxTableRows = 1;
  assert.throws(() => compileDeckHtml(overLimit), /table-row limit/);
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
