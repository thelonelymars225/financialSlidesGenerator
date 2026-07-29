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

## 2026-07-25 — Supabase database and object-storage foundation

**Decision:** Use the existing hosted Supabase project in Frankfurt
(`eu-central-1`) for production PostgreSQL and private object storage. Keep
SQLite as the secretless local fallback.

**Isolation:** Application tables live in a private schema with RLS enabled and
no `anon` or `authenticated` grants. Files remain in private buckets and flow
through the API until authentication and per-user storage policies are ready.

**Deferred:** Authentication UX, retention periods, deletion schedules, direct
browser uploads, queues/Cron, and vector storage remain separate decisions.
RAG is still outside the first slide-generation vertical slice.

**Revisit when:** Deployment measurements show the database-backed worker claim
path is insufficient, direct uploads materially reduce API cost, or approved
retention requirements require scheduled cleanup.

## 2026-07-29 — Privacy-minimizing MVP retention

**Decision:** Default source content and generated outputs to 24 hours, allow
operators to configure one to 8,760 hours, and let an owner delete either data
class immediately. Preserve content-free job metadata for idempotency and
diagnostics. Enforce expiry during ordinary API traffic until a production
scheduler is selected.

**Access and audit:** Deletion uses the existing owner boundary and returns
`404` across owners. Audit events contain action, resource ID, a hashed owner
identifier, and deletion count only. Hosted analysis requires an explicit
operator assertion that provider retention is disabled.

**Limitations:** `X-Owner-ID` is not production authentication, SQLite does not
add database-level encryption, and lazy cleanup cannot guarantee wall-clock
deletion when there is no API traffic. Production launch requires verified
identity, scheduled cleanup, and durable restricted audit storage.

**Revisit when:** Product/legal requirements specify a different period,
enterprise customers require legal holds, or the production platform supplies a
native lifecycle policy that can replace application cleanup.
