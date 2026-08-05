# Native extraction fixtures

These fixtures are synthetic and contain no company or personal data.

- `native-financial-report.pdf.b64` is a one-page born-digital PDF with a heading and a
  simple financial table.
- `encrypted-financial-report.pdf.b64` is the same synthetic PDF encrypted with the
  fixture-only password `secret`.
- `finance-aware-cases.json` covers an income statement, balance sheet, cash-flow statement,
  segment table, KPI table, multi-period comparison, restated value, and actual-versus-forecast
  table. The golden-case test retrieves its required facts using only the v0.2 fact layer.

The files are stored as Base64 text so fixture provenance remains reviewable in Git.
