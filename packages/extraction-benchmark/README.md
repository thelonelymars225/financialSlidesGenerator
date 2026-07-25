# Extraction benchmark

This package is the shared evaluation surface for local parsing, OCR, document
APIs, and selective VLM/model routes. It extends the repository's cheap/local
model evaluation work instead of creating a second model benchmark.

All committed fixtures are synthetic. The deterministic provider replays
versioned canonical outputs for native parsing, OCR, document-API, and selective
VLM routes so CI can detect metric, contract, provenance, and critical-number
regressions without credentials or provider calls. Recorded route latency is a
fixture threshold check, not a claim about a currently selected vendor.

## Deterministic CI benchmark

```bash
pnpm --filter @financial-slides/extraction-benchmark benchmark
pnpm --filter @financial-slides/extraction-benchmark test
```

The report covers:

- normalized text accuracy;
- table-cell accuracy;
- exact numeric fidelity;
- reading order;
- page, section, and bounding-box preservation;
- canonical structured-output validation;
- latency and estimated variable cost;
- dedicated exact checks for values, negative signs, percentages, units,
  periods, and totals.

The root `pnpm test` command discovers this package automatically, so the
deterministic subset runs in the existing Continuous Improvement workflow.

## Explicit live-provider mode

Live execution is opt-in twice: set an allow flag and provide a local adapter
module. The module must export `async function run(fixture, source)` and return
`{ document, route, durationMs, estimatedCostUsd }`.

```bash
EXTRACTION_BENCHMARK_ALLOW_LIVE=1 \
EXTRACTION_BENCHMARK_PROVIDER_MODULE=/absolute/path/to/provider.mjs \
pnpm --filter @financial-slides/extraction-benchmark benchmark:live
```

Do not commit credentials, confidential source files, or raw provider
responses. A live adapter should obtain secrets from its runtime and normalize
every result into the canonical extracted-document contract.
