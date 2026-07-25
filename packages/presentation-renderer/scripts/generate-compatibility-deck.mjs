import { mkdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { PresentationRenderer } from "../src/index.js";

const packageDir = resolve(fileURLToPath(new URL("..", import.meta.url)));
const repositoryRoot = resolve(packageDir, "../..");
const deck = JSON.parse(
  await readFile(
    resolve(repositoryRoot, "packages/contracts/examples/slide-spec-v0.1.json"),
    "utf8",
  ),
);

deck.slides.push({
  id: "slide-image-compatibility",
  order: 5,
  layoutId: "insight",
  title: "Raster assets remain selectable",
  components: [
    {
      id: "compatibility-image",
      type: "image",
      region: "body",
      sources: [],
      assetRef: "asset:compatibility-marker",
      altText: "Teal compatibility marker",
    },
  ],
});

const outputPath = resolve(packageDir, "tmp/renderer-compatibility.pptx");
const marker =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAAAGUExURQ2UiP///xUskwcAAAABYktHRAH/Ai3eAAAAB3RJTUUH6gcZECQVZCnwfAAAAAtJREFUCNdjYEAFAAAQAAGhxSHBAAAAAElFTkSuQmCC";
await mkdir(resolve(packageDir, "tmp"), { recursive: true });
const result = await new PresentationRenderer().render(deck, {
  outputPath,
  assets: { "asset:compatibility-marker": marker },
});

console.log(JSON.stringify(result, null, 2));
