import { compileDeckHtml } from "@financial-slides/presentation-harness";

import { PresentationRenderer } from "./index.js";

const outputPath = process.argv[2];
if (!outputPath) throw new Error("output path is required");
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const deckSpec = JSON.parse(Buffer.concat(chunks).toString("utf8"));
compileDeckHtml(deckSpec);
await new PresentationRenderer().render(deckSpec, { outputPath });
