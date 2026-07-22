# Shared contracts

This package defines the versioned data boundaries between ingestion, extraction,
analysis, layout, and rendering. Contracts are provider-neutral: they may describe
output from local parsing, OCR, a document API, or a vision model without importing
an SDK or exposing provider-specific response objects.

## Extracted Document v0.1

`schemas/extracted-document-v0.1.schema.json` is the canonical result of source
extraction. It preserves:

- document, page, section, and bounding-box provenance;
- ordered text, table, and image blocks;
- table cell structure and confidence;
- the generic extraction method plus optional provider/model diagnostics;
- original displayed financial values beside parsed numeric values; and
- machine-readable warnings for review and escalation.

JSON Schema enforces the portable shape. `scripts/contract-validation.mjs` adds
cross-field checks that JSON Schema cannot express clearly, including unique page
and block identities, page-consistent provenance, valid geometry, and table bounds.

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
