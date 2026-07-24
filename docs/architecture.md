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
born-digital PDFs through replaceable local parser adapters. Every route emits
Extracted Document v0.1 plus separate duration, route, and external-cost
telemetry. OCR and model-backed fallbacks remain downstream escalation paths.

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

## Durable extraction-job boundary

- FastAPI controllers validate transport input and delegate to an application
  service; they never perform extraction inside the request.
- Immutable job models define queued, running, succeeded, failed, and cancelled
  states. State transitions, idempotency keys, retry decisions, and exponential
  backoff are deterministic.
- Repository, queue, source-store, and result-store protocols keep infrastructure
  replaceable. The secretless baseline uses one SQLite adapter so API and worker
  processes can reopen the same durable state after restart.
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
