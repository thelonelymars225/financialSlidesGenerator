# financialSlidesGenerator

An affordable, source-grounded service that turns company reports into editable
PowerPoint presentations. The repository is a monorepo so the web experience,
analysis services, presentation engine, and shared contracts can evolve together
without becoming tightly coupled.

The product direction and MVP boundaries come from
[`financialSlidesGenerator_BRD_v0.1.docx`](docs/financialSlidesGenerator_BRD_v0.1.docx).

## Repository map

```text
apps/
  web/                         Customer-facing web application
services/
  api/                         Python API and job orchestration
  worker/                      Long-running generation jobs
packages/
  contracts/                   Language-neutral JSON contracts
  extraction-benchmark/        Safe extraction quality and cost regression suite
  presentation-harness/       Layout selection, fitting, and preflight
  presentation-renderer/      Replaceable PowerPoint renderer adapter
docs/                          BRD, architecture, and decision records
```

See [docs/architecture.md](docs/architecture.md) for why these boundaries exist.
Cloud hosting instructions live in [docs/deployment.md](docs/deployment.md).
Reusable OCR and PowerPoint export interfaces are documented in
[docs/modular-ocr-and-export.md](docs/modular-ocr-and-export.md).

## Prerequisites

- Node.js 22 or newer
- pnpm 11 or newer
- Python 3.12 or newer
- uv
- Tesseract 5 with the English language data (`eng`) for local OCR

## First-time setup

```bash
pnpm install
uv sync --all-packages --all-extras
cp .env.example .env
```

## Everyday commands

```bash
pnpm dev          # start React on :3000 and FastAPI on :8000
pnpm build        # create the production frontend build
pnpm check        # type-check React and lint Python
pnpm test         # run web, API, and worker tests
pnpm test:web     # run frontend tests
pnpm test:api     # run FastAPI tests
pnpm test:worker  # run extraction worker tests
pnpm verify       # run checks, all tests, and the production build
```

Individual workspaces can also be run directly:

```bash
pnpm --filter @financial-slides/web dev
uv run --package financial-slides-api uvicorn financial_slides_api.main:app --reload
pnpm --filter @financial-slides/extraction-benchmark benchmark
```

## Optional hosted analysis

Local development and CI use the deterministic analysis provider by default. To
use an OpenAI-compatible hosted API, copy `.env.example` to `.env` and set:

```dotenv
MODEL_PROVIDER=openai-compatible
MODEL_BASE_URL=https://your-provider.example/v1
MODEL_API_KEY=your-local-secret
MODEL_NAME=your-model
MODEL_DATA_RETENTION_DISABLED=true
```

For DeepSeek, only the provider and key are required; the adapter defaults to
`deepseek-v4-flash` at `https://api.deepseek.com`:

```dotenv
MODEL_PROVIDER=deepseek
MODEL_API_KEY=your-local-secret
MODEL_DATA_RETENTION_DISABLED=true
```

Keep `.env` local and server-side. The committed example contains no key, and
tests never make paid calls. Set the retention assertion only after verifying
provider account settings; hosted analysis refuses to start otherwise. Optional
per-million-token prices in `.env` enable cost telemetry without changing the
provider adapter. Privacy defaults and deletion behavior are documented in
[`docs/privacy.md`](docs/privacy.md).

## Reusable local OCR and export

The default PDF path uses native extraction first and invokes local Tesseract
only for scanned or low-text pages. This keeps external OCR cost at zero. For a
larger system that already rasterizes pages, `LocalOcrService.extract_image`
accepts encoded image bytes and pixel dimensions directly, with byte, pixel,
and time limits.

The presentation package provides both an in-memory exporter and the existing
file renderer. Use `exportPresentation(deckSpec)` when integrating with object
storage, an API response, or a queue; use `PresentationRenderer.render` for a
filesystem artifact. Both consume the same renderer-neutral DeckSpec contract.

Queued extraction runs outside the web request. Process a bounded batch from
the durable secretless queue with:

```bash
uv run --package financial-slides-api python -m financial_slides_api.worker --limit 4
```

Set `FINANCIAL_SLIDES_JOB_DB` to a SQLite path shared by the API and worker. The
repository, queue, source-store, and result-store ports remain replaceable when
managed cloud infrastructure is selected.

## Adding dependencies

Install a dependency in the workspace that directly imports and uses it. Avoid
installing application dependencies at the repository root.

### React frontend

Frontend dependencies belong to `apps/web/package.json`:

```bash
# Runtime dependency
pnpm --filter @financial-slides/web add <package>

# Development-only dependency
pnpm --filter @financial-slides/web add --save-dev <package>
```

For example:

```bash
pnpm --filter @financial-slides/web add react-hook-form
```

### FastAPI backend

Backend dependencies belong to `services/api/pyproject.toml` and are locked in
the root `uv.lock`:

```bash
# Runtime dependency
uv add --package financial-slides-api <package>

# Development-only dependency
uv add --package financial-slides-api --dev <package>
```

For example:

```bash
uv add --package financial-slides-api sqlalchemy
```

### Presentation harness

Presentation-generation dependencies belong to
`packages/presentation-harness/package.json`:

```bash
# Runtime dependency
pnpm --filter @financial-slides/presentation-harness add <package>

# Development-only dependency
pnpm --filter @financial-slides/presentation-harness add --save-dev <package>
```

For example:

```bash
pnpm --filter @financial-slides/presentation-harness add pptxgenjs
```

### Repository-wide tools

Only tools used by the entire repository, such as formatters or task runners,
belong at the root:

```bash
pnpm add --workspace-root --save-dev <package>
```

After adding or removing dependencies, commit the relevant manifest and its
lockfile together:

- JavaScript: the workspace `package.json` and `pnpm-lock.yaml`
- Python: the workspace `pyproject.toml` and `uv.lock`

## Current status

The monorepo now includes durable extraction jobs, local OCR fallback, hosted or
deterministic analysis, source-grounded slide generation, editable PowerPoint
export, operational health checks, and production deployment workflows. Product
choices that still require evidence are recorded in [docs/decisions.md](docs/decisions.md).

## Git workflow

`main` is for approved releases. Ongoing integration happens on `dev`, and
short-lived feature branches start from `dev`.

Never commit customer reports, generated customer files, credentials, or private
evaluation fixtures. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change.
