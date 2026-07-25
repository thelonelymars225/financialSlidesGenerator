import { pathToFileURL } from "node:url";
import { readJson } from "./runner.mjs";

export function deterministicProvider(manifestUrl) {
  return {
    name: "recorded-deterministic",
    async run(fixture) {
      const document = await readJson(new URL(fixture.deterministicOutput, manifestUrl));
      return {
        document,
        route: fixture.route,
        durationMs: fixture.deterministicDurationMs,
        estimatedCostUsd: 0,
      };
    },
  };
}

export async function liveProviderFromEnvironment() {
  if (process.env.EXTRACTION_BENCHMARK_ALLOW_LIVE !== "1") {
    throw new Error("Live mode requires EXTRACTION_BENCHMARK_ALLOW_LIVE=1.");
  }
  const modulePath = process.env.EXTRACTION_BENCHMARK_PROVIDER_MODULE;
  if (!modulePath) {
    throw new Error("Live mode requires EXTRACTION_BENCHMARK_PROVIDER_MODULE.");
  }
  const module = await import(pathToFileURL(modulePath).href);
  if (typeof module.run !== "function") {
    throw new Error("The live provider module must export async function run(fixture, source).");
  }
  return { name: module.name ?? "opt-in-live-provider", run: module.run };
}
