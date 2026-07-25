# Selective document API and VLM fallback

Local native parsing and OCR remain the default extraction routes. A configured
document-processing API or low-cost vision model receives only a rendered image
and existing evidence for an explicitly selected page. The original file and
unselected pages are not included in the provider request.

## Routing and limits

Provider fallback is eligible only when deterministic routing records one of
these reasons:

- OCR confidence below `0.85`;
- local OCR failure;
- a materially sized visual on a born-digital page; or
- an ambiguous table layout with at least 25% empty cells.

The worker defaults to at most five provider pages, two attempts per provider,
12,000 total provider tokens, USD 0.25 variable cost, ten seconds per call, and
the existing 30-second overall extraction deadline. Providers receive their
remaining token, cost, and timeout budgets with each page request. Exceeding a
budget preserves the local page and emits a safe typed warning.

Document APIs are preferred for OCR and layout failures. VLMs are preferred for
complex visuals. Either interface remains replaceable, and no live provider is
configured by default.

## Contract and evidence safety

Provider pages must satisfy Extracted Document v0.1 when merged back into the
local result. Every block and table-cell source must point to the selected page,
and every block must identify the configured provider, model, and either the
`document_api` or `vlm` extraction method.

When reliable native/OCR evidence contains financial values, the fallback must
preserve those values. A mismatch rejects the provider page. Low-confidence OCR
is allowed to be corrected, but the canonical contract and page provenance are
still mandatory.

## Sensitive-data handling

- Adapters must declare provider-side retention disabled; retained-data
  providers are rejected during configuration.
- Credentials are server-only and must never be committed, logged, placed in a
  frontend environment variable, or embedded in a fixture.
- Requests contain one selected page only. Provider responses and source images
  must not be logged.
- CI uses mock adapters and synthetic, non-sensitive fixtures.
- Live adapters remain opt-in until privacy terms, region, deletion behavior,
  accuracy, latency, and cost are approved for the provider.

This boundary limits what is sent to an external service. It does not replace
the future project-wide retention, deletion, authentication, and audit controls.
