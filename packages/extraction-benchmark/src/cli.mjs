import { deterministicProvider, liveProviderFromEnvironment } from "./providers.mjs";
import { runBenchmark } from "./runner.mjs";

const manifestUrl = new URL("../fixtures/manifest.json", import.meta.url);
const live = process.argv.includes("--live");
const provider = live
  ? await liveProviderFromEnvironment()
  : deterministicProvider(manifestUrl);
const report = await runBenchmark({ manifestUrl, provider });

process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (report.summary.failed > 0) process.exitCode = 1;
