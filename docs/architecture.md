# Monorepo architecture

## Guiding rule

The model produces cited business analysis. Deterministic software validates,
fits, renders, and checks the presentation. Shared contracts sit between those
responsibilities so either side can be replaced independently.

## Workspace responsibilities

### `apps/web`

Owns authentication screens, uploads and pasted input, job progress, preview,
correction requests, and downloads. It should call the API rather than reach into
storage, model providers, or renderer packages directly.

### `services/api`

Owns the public API, entitlement checks, job creation, artifact metadata, and
orchestration. Slow generation work must be handed to a worker instead of being
performed inside a request.

### `services/worker`

Owns long-running stages: extraction, retrieval, analysis, validation, layout,
preflight, rendering, and bounded repair. Queue technology remains undecided.
Native extraction currently routes pasted text and signature-verified,
born-digital PDFs through replaceable local parser adapters. Scanned and
low-text PDF pages use bounded local Tesseract OCR with confidence-based review
warnings. Every route emits Extracted Document v0.1 plus separate duration,
route, and external-cost telemetry. Model-backed fallbacks remain downstream
escalation paths.

### `packages/contracts`

Contains versioned JSON Schema files and examples shared across Python and
TypeScript. The Extracted Document contract is the provider-neutral boundary
between parsers and downstream retrieval or analysis; Analysis objects must not
contain parser responses or renderer-specific HTML.

### `packages/presentation-harness`

Owns the approved layout registry, slot limits, DeckSpec compilation, browser
preflight, deterministic fitting, and targeted-repair requests.

### `packages/presentation-renderer`

Defines the stable renderer interface and will contain the selected Node-based
PowerPoint adapter. Keeping it isolated allows renderer replacement after
editability and compatibility benchmarks.

### `fixtures/golden`

Holds safe inputs and expected facts, citations, required findings, and forbidden
claims. No real confidential company reports belong here.

## Intended generation flow

```text
web -> API -> job queue -> worker
                         |-> extract to Extracted Document v0.1
                         |-> retrieve source sections with preserved provenance
                         |-> create and validate Analysis v0.1
                         |-> compile a renderer-neutral DeckSpec
                         |-> preflight and fit approved layouts
                         `-> renderer adapter -> validate PPTX -> artifact storage
```

## Dependency direction

- Applications may depend on contracts.
- The harness may depend on contracts.
- Renderer adapters may depend on contracts and the renderer interface.
- Contracts must not depend on applications, services, model SDKs, or renderers.
- Python services communicate with Node presentation code through versioned data
  and a future process/queue boundary, not by importing TypeScript internals.

## Native extraction boundary

- File signatures, not filename extensions, select a parser.
- Parser adapters own third-party library effects; routing, limits, and error
  mapping remain deterministic and directly testable.
- The FastAPI application service may invoke the worker extraction boundary,
  while HTTP controllers remain free of parser logic.
- Local routes report zero external-service cost. Encrypted, corrupt,
  unsupported, oversized, over-page-limit, and timed-out inputs return stable
  typed errors.
- OCR is English-only until Arabic enters the approved MVP. It is capped
  separately from the document page limit and flags failed or low-confidence
  pages instead of silently accepting them.

## Durable extraction-job boundary

- FastAPI controllers validate transport input and delegate to an application
  service; they never perform extraction inside the request.
- Immutable job models define queued, running, succeeded, failed, and cancelled
  states. State transitions, idempotency keys, retry decisions, and exponential
  backoff are deterministic.
- Repository, queue, source-store, and result-store protocols keep infrastructure
  replaceable. The secretless baseline uses one SQLite adapter. Production uses
  the same ports through PostgreSQL in the private `financial_slides` schema;
  worker claims use row locks with `SKIP LOCKED` so concurrent workers cannot
  process the same job.
- Source bytes are persisted with the job rather than referenced from a
  developer laptop. A cloud persistent volume can host the baseline database;
  managed queue and object-store adapters can replace it without changing HTTP
  contracts or extraction logic.
- The worker claims queued jobs atomically, enforces bounded attempts and work
  per run, emits the canonical extracted-document contract, records route,
  duration, retry count, and estimated external cost, and stores typed failures.
- `X-Owner-ID` scopes status, result, and cancellation access. The development
  default is `local-development`; production authentication remains a separate
  adapter concern.

## Supabase persistence boundary

- The hosted `financial-slides-generator` project in Frankfurt (`eu-central-1`)
  is the production database and object-storage foundation.
- Application tables live in the private `financial_slides` schema, have RLS
  enabled for defense in depth, and are not part of the browser-facing Data API.
- `source-documents` and `generated-presentations` are private buckets with
  explicit MIME and size limits. The API mediates access; browser policies and
  signed URLs wait for the authentication ticket.
- `DATABASE_URL` selects the PostgreSQL adapter in hosted environments. SQLite
  remains the default when no production database URL is configured.
- Secret or service-role credentials are server-only and never use a frontend
  environment-variable prefix.
