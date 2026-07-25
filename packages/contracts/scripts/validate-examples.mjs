import { readdir, readFile } from "node:fs/promises";

import { validateContract } from "./contract-validation.mjs";

const examplesDirectory = new URL("../examples/", import.meta.url);
const exampleFiles = (await readdir(examplesDirectory)).filter((fileName) => fileName.endsWith(".json"));

for (const fileName of exampleFiles) {
  const example = JSON.parse(await readFile(new URL(fileName, examplesDirectory), "utf8"));
  const contractName = fileName.startsWith("analysis-")
    ? "analysis"
    : fileName.startsWith("slide-spec-")
      ? "slideSpec"
      : "extractedDocument";
  const result = await validateContract(contractName, example);
  if (!result.valid) {
    throw new Error(`${fileName} is invalid:\n- ${result.errors.join("\n- ")}`);
  }
}

console.log(`${exampleFiles.length} contract examples passed schema and semantic validation.`);
