import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  analyzeMeasurements,
  createRepairPlan,
  layoutRegistry,
  runBrowserPreflight,
} from "../src/index.js";

async function fixture() {
  return JSON.parse(
    await readFile(
      new URL("../../contracts/examples/slide-spec-v0.1.json", import.meta.url),
      "utf8",
    ),
  );
}

function element(componentId, bounds, overrides = {}) {
  return {
    componentId,
    region: "body",
    bounds,
    clientWidth: bounds.right - bounds.left,
    clientHeight: bounds.bottom - bounds.top,
    scrollWidth: bounds.right - bounds.left,
    scrollHeight: bounds.bottom - bounds.top,
    fontSize: 24,
    lineHeight: 31.2,
    padding: 12,
    overflowX: "hidden",
    overflowY: "hidden",
    assetMissing: false,
    ...overrides,
  };
}

test("detects missing assets, bounds, clipped overflow, and overlap", () => {
  const snapshot = {
    slides: [
      {
        slideId: "slide-1",
        bounds: { left: 0, top: 0, right: 1280, bottom: 720 },
        elements: [
          element("one", { left: 20, top: 20, right: 400, bottom: 300 }, {
            scrollHeight: 340,
          }),
          element("two", { left: 350, top: 200, right: 1300, bottom: 500 }, {
            assetMissing: true,
          }),
        ],
      },
    ],
  };

  const failures = analyzeMeasurements(snapshot);
  assert.deepEqual(
    failures.map(({ code }) => code).sort(),
    ["missing-asset", "out-of-bounds", "overflow", "overlap"],
  );
  assert.equal(failures.find(({ code }) => code === "overflow").clipped, true);
});

test("auto-fit is deterministic and respects minimum font and spacing", async () => {
  const deck = await fixture();
  const overflowing = {
    slides: [
      {
        slideId: deck.slides[0].id,
        bounds: { left: 0, top: 0, right: 1280, bottom: 720 },
        elements: [
          element(
            deck.slides[0].components[0].id,
            { left: 72, top: 124, right: 1208, bottom: 188 },
            { clientHeight: 64, scrollHeight: 180, padding: 10 },
          ),
        ],
      },
    ],
  };
  const passed = { slides: [] };
  const html = [];
  const page = {
    async setContent(value) {
      html.push(value);
    },
    async evaluate() {
      return html.length === 1 ? overflowing : passed;
    },
  };

  const report = await runBrowserPreflight(deck, { page });

  assert.equal(report.status, "passed");
  assert.equal(report.passes, 2);
  assert.deepEqual(report.fitOverrides[deck.slides[0].components[0].id], {
    fontSize: 16,
    lineHeight: 1.3,
    padding: 4,
  });
  assert.match(html[1], /font-size:16px;line-height:1.3;padding:4px/);
});

test("repair requests are slide-specific, reason-specific, and capped", async () => {
  const deck = await fixture();
  const failures = [
    {
      code: "overflow",
      slideId: deck.slides[0].id,
      componentId: deck.slides[0].components[0].id,
    },
    {
      code: "missing-asset",
      slideId: deck.slides[0].id,
      componentId: "image",
    },
  ];

  const plan = createRepairPlan(deck, failures, {
    attempt: 1,
    policy: { maxRepairAttempts: 2 },
    layoutRegistry,
  });

  assert.equal(plan.status, "repair-required");
  assert.equal(plan.attemptsRemaining, 1);
  assert.deepEqual(plan.requests[0].reasons, ["missing-asset", "overflow"]);
  assert.equal(plan.requests.length, 1);
});

test("repeated failure falls back only to a compatible approved layout", async () => {
  const deck = await fixture();
  const slide = deck.slides[0];
  const plan = createRepairPlan(
    deck,
    [{ code: "overflow", slideId: slide.id, componentId: slide.components[0].id }],
    { attempt: 2, layoutRegistry },
  );

  assert.equal(plan.status, "fallback");
  assert.deepEqual(plan.fallbacks, [{ slideId: slide.id, layoutId: "insight" }]);
  assert.equal(plan.deckSpec.slides[0].layoutId, "insight");
  assert.equal(deck.slides[0].layoutId, "executive-summary");
});

test("repeated failure returns an actionable error when no fallback is safe", async () => {
  const deck = await fixture();
  const slide = deck.slides.find(({ layoutId }) => layoutId === "chart");
  const plan = createRepairPlan(
    deck,
    [{ code: "overlap", slideId: slide.id, componentIds: ["a", "b"] }],
    { attempt: 2, layoutRegistry },
  );

  assert.equal(plan.status, "failed");
  assert.deepEqual(plan.errors[0].reasons, ["overlap"]);
  assert.match(plan.errors[0].message, /No safe fallback for layout chart/);
});
