import { readFile } from "node:fs/promises";

const example = JSON.parse(await readFile(new URL("../examples/analysis-v0.1.json", import.meta.url)));
if (example.schemaVersion !== "0.1" || !Array.isArray(example.facts)) {
  throw new Error("Analysis example does not satisfy the minimum v0.1 contract.");
}
console.log("Contract examples are valid JSON with the expected version.");
