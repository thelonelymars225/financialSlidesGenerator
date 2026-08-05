# Shared contracts

This package defines the versioned data boundaries between ingestion, extraction,
analysis, layout, and rendering. Contracts are provider-neutral: they may describe
output from local parsing, OCR, a document API, or a vision model without importing
an SDK or exposing provider-specific response objects.

## Extracted Document v0.2

`schemas/extracted-document-v0.2.schema.json` keeps every raw v0.1 page and block and adds a
finance-aware fact layer. Each fact carries the displayed value, parsed and normalized values,
stable metric identity, statement type, period, unit, currency, scale, entity/segment scope,
scenario, restatement status, table-header lineage, source geometry, and confidence per field.

Ambiguity is data rather than an implicit guess: nullable normalized fields preserve the raw
displayed value, fact warnings explain missing or failed mappings, and `factValidation` collects
document-level duplicate, conflict, parse, unit, period, and reconciliation findings. New
extraction producers emit v0.2. The v0.1 schema remains valid for stored results and provider page
responses during migration.

## Extracted Document v0.1

`schemas/extracted-document-v0.1.schema.json` is the backward-compatible raw extraction boundary.
It preserves:

- document, page, section, and bounding-box provenance;
- ordered text, table, and image blocks;
- table cell structure and confidence;
- the generic extraction method plus optional provider/model diagnostics;
- original displayed financial values beside parsed numeric values; and
- machine-readable warnings for review and escalation.

JSON Schema enforces the portable shape. `scripts/contract-validation.mjs` adds
cross-field checks that JSON Schema cannot express clearly, including unique page
and block identities, page-consistent provenance, valid geometry, and table bounds.

## Analysis v0.2

`schemas/analysis-v0.2.schema.json` is the evidence-grounded boundary between
financial analysis and slide planning. It adds:

- normalized metrics with displayed values, periods, units, scale factors,
  evidence, and confidence;
- findings typed as facts, trends, risks, opportunities, or recommendations;
- slide intents that reference validated findings and metrics;
- deterministic checks for identifiers, references, source grounding, and unit
  normalization; and
- code-checked sum, difference, ratio, and percentage-change calculations.

`analysis-v0.1.schema.json` remains available and valid for backward compatibility.
New producers should emit v0.2. Unknown versions are rejected rather than guessed.
Calculation operands are ordered: difference is first minus second, ratio is first
divided by second, and percentage change is baseline followed by current value.
Currency metrics normalize through their declared scale factor; percentages use
`0.01`, while counts and ratios use `1`.

## Slide Specification v0.1

`schemas/slide-spec-v0.1.schema.json` is the narrow boundary between analysis,
deterministic HTML compilation, and PowerPoint rendering. Models may select only
approved layouts, regions, and component types; they cannot emit HTML, CSS,
JavaScript, remote URLs, or renderer instructions.

The contract caps deck, component, text, table, chart, series, source, and asset
sizes. Financial values retain their displayed text, signed numeric value,
normalized value, currency or unit, scale factor, period, and source references.
Semantic validation checks identity and order uniqueness, layout/component
compatibility, declared source documents, table and chart dimensions, period
validity, normalization, and unsafe markup.

## Versioning rules

- Published schema files are immutable. A behavior-changing revision gets a new
  schema file and `schemaVersion` value.
- A compatible revision may add optional fields or broaden documented inputs. It
  must not change the meaning of an existing field.
- Adding a required field, removing a field, narrowing accepted values, or changing
  semantics is breaking and requires a new major contract version.
- Producers declare exactly one version. Consumers reject unknown versions rather
  than guessing, and migrations must be explicit and tested.
- Raw displayed text and provenance remain available across migrations even when a
  normalized numeric value or derived representation changes.

## Validation

From the repository root:

```bash
pnpm --filter @financial-slides/contracts check
pnpm --filter @financial-slides/contracts test
```

Examples cover pasted text, a native PDF table, an OCR scan, and a VLM-described
chart. They are synthetic and contain no confidential company data.
