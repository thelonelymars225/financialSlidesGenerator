# Open decisions

The BRD intentionally leaves these choices open. Resolve them with a small spike
and measurable acceptance criteria before adopting a production dependency.

| Decision | Evidence required | Status |
| --- | --- | --- |
| First report type and deck audience | Representative safe fixtures and reference deck | Open |
| Supported input formats and limits | Extraction quality, latency, and cost tests | Open |
| PowerPoint renderer | Editability, compatibility, licensing, and layout fidelity | Open |
| Primary and fallback models | Golden-set accuracy, citations, latency, and cost | Open |
| Per-job or persistent retrieval | Measured cross-document need | Open |
| Queue and worker platform | Reliability and deployment constraints | Open |
| Database and object storage | Region, retention, isolation, and deletion needs | Open |
| Billing provider and plans | Real unit-cost telemetry and market validation | Open |

When a decision is made, add a dated record beneath this table describing the
choice, alternatives, evidence, consequences, and conditions for revisiting it.

## 2026-07-25 — Extraction default and escalation evidence

**Decision:** Use deterministic local parsing as the default route for pasted
text and born-digital PDFs. Keep OCR, document APIs, and selective VLM
extraction behind the same canonical contract and shared extraction benchmark;
none becomes a default until its live measurements pass the same thresholds.

**Evidence:** The committed secretless regression suite covers born-digital
text, a financial table, a scanned page, a mixed PDF, and a chart. It validates
contract output, text accuracy, table cells, exact financial values, reading
order, source locations, latency, and estimated cost. The deterministic baseline
passes 6 of 6 route fixtures at zero external execution cost.

**Escalation thresholds:**

- Route a page to OCR when native extraction reports an image-only page, fewer
  than 40 useful characters, or text bounding boxes cover less than 1.5% of the
  page area.
- Require review or a stronger fallback below 0.85 extraction confidence, below
  0.98 table-cell accuracy, on any failed critical-number check, or when source
  locations are missing.
- Permit document API or VLM evaluation only for the affected pages after local
  extraction/OCR is insufficient; keep live runs explicitly opt-in and record
  latency and variable cost.

**Consequences:** The cheap/local-model benchmark and extraction routing use one
fixture manifest, metric implementation, and provider interface. CI runs only
the deterministic subset. Live adapters must be supplied explicitly and may
not write credentials or confidential responses to the repository.

**Unresolved weaknesses:** Arabic OCR scope and quality, rotated/low-resolution
scan performance, complex merged table cells, chart-number verification, and
real document-API/VLM latency and cost still need measured provider results.
