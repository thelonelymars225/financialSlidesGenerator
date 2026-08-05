import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { test } from "node:test";

import JSZip from "jszip";

import { PresentationRenderer } from "../src/index.js";
import { visualFixture } from "../../presentation-harness/test/visual-fixture.mjs";

const examplePath = resolve(
  import.meta.dirname,
  "../../contracts/examples/slide-spec-v0.1.json",
);
const marker =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAAAGUExURQ2UiP///xUskwcAAAABYktHRAH/Ai3eAAAAB3RJTUUH6gcZECQVZCnwfAAAAAtJREFUCNdjYEAFAAAQAAGhxSHBAAAAAElFTkSuQmCC";

async function exampleDeck() {
  return JSON.parse(await readFile(examplePath, "utf8"));
}

test("renders editable text, table, chart, notes, and image OOXML", async () => {
  const deck = await exampleDeck();
  deck.slides.push({
    id: "slide-image",
    order: 5,
    layoutId: "insight",
    title: "Image compatibility",
    components: [
      {
        id: "image",
        type: "image",
        region: "body",
        sources: [],
        assetRef: "asset:marker",
        altText: "Compatibility marker",
      },
    ],
  });
  const outputPath = resolve(tmpdir(), `renderer-${crypto.randomUUID()}.pptx`);

  const result = await new PresentationRenderer().render(deck, {
    outputPath,
    assets: { "asset:marker": marker },
  });
  const archive = await JSZip.loadAsync(await readFile(outputPath));
  const files = Object.keys(archive.files);
  const slideXml = await archive.file("ppt/slides/slide3.xml").async("string");
  const allSlideXml = (
    await Promise.all(
      files
        .filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name))
        .map((name) => archive.file(name).async("string")),
    )
  ).join("");

  assert.deepEqual(result, { outputPath, warnings: [] });
  assert.equal(files.filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name)).length, 5);
  assert.ok(files.some((name) => name.startsWith("ppt/charts/chart")));
  assert.ok(files.some((name) => name.startsWith("ppt/media/image")));
  assert.match(slideXml, /Quarterly revenue/);
  assert.match(slideXml, /Q2 2026/);
  assert.match(allSlideXml, /Sources:/);
  assert.match(allSlideXml, /17324D/);
  assert.match(allSlideXml, /0F766E/);
  assert.match(allSlideXml, /F3F7F5/);
  assert.ok(files.some((name) => name.startsWith("ppt/notesSlides/notesSlide")));
});

test("rejects an unapproved theme instead of accepting arbitrary styling", async () => {
  const deck = await exampleDeck();
  deck.themeId = "model-authored-theme";

  await assert.rejects(
    () =>
      new PresentationRenderer().render(deck, {
        outputPath: resolve(tmpdir(), "unknown-theme.pptx"),
      }),
    /Unknown presentation theme/,
  );
});

test("uses an editable bar fallback for waterfall charts", async () => {
  const deck = await exampleDeck();
  deck.slides[3].components[0].chartType = "waterfall";
  const outputPath = resolve(tmpdir(), `renderer-${crypto.randomUUID()}.pptx`);

  const result = await new PresentationRenderer().render(deck, { outputPath });

  assert.deepEqual(result.warnings, [
    "Waterfall charts use an editable bar-chart fallback.",
  ]);
});

test("rejects unresolved and remote image assets", async () => {
  const deck = await exampleDeck();
  deck.slides[0].components = [
    {
      id: "image",
      type: "image",
      region: "body",
      sources: [],
      assetRef: "asset:missing",
      altText: "Missing",
    },
  ];

  await assert.rejects(
    () =>
      new PresentationRenderer().render(deck, {
        outputPath: resolve(tmpdir(), "missing.pptx"),
      }),
    /Missing image asset/,
  );
  await assert.rejects(
    () =>
      new PresentationRenderer().render(deck, {
        outputPath: resolve(tmpdir(), "remote.pptx"),
        assets: { "asset:missing": "https://example.com/image.png" },
      }),
    /Remote image URLs are not allowed/,
  );
});

test("renders polished layouts as editable, cited decks across every density", async () => {
  for (const density of ["concise", "balanced", "detailed"]) {
    const deck = visualFixture(density);
    deck.slides[1].title = "An intentionally long management headline that must remain readable without losing its complete source wording";
    const outputPath = resolve(tmpdir(), `polished-${density}-${crypto.randomUUID()}.pptx`);

    const result = await new PresentationRenderer().render(deck, { outputPath });
    const archive = await JSZip.loadAsync(await readFile(outputPath));
    const files = Object.keys(archive.files);
    const slideXml = (
      await Promise.all(files.filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name)).map((name) => archive.file(name).async("string")))
    ).join("");
    const notesXml = (
      await Promise.all(files.filter((name) => /^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(name)).map((name) => archive.file(name).async("string")))
    ).join("");

    assert.deepEqual(result, { outputPath, warnings: [] });
    assert.equal(files.filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name)).length, 8);
    assert.ok(files.some((name) => name.startsWith("ppt/charts/chart")), "chart remains editable");
    assert.match(slideXml, /Business-unit performance/);
    assert.match(slideXml, /B3261E/);
    assert.match(notesXml, /\[Sources\]/);
    assert.match(notesXml, /\[Full title\]/);
    assert.match(notesXml, /complete source wording/);
    assert.match(notesXml, /p\.10/);
  }
});
