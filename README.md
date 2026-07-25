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
pnpm test         # run frontend and API tests
```

Individual workspaces can also be run directly:

```bash
pnpm --filter @financial-slides/web dev
uv run --package financial-slides-api uvicorn financial_slides_api.main:app --reload
pnpm --filter @financial-slides/extraction-benchmark benchmark
```

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

This is the initial monorepo foundation. It includes a working API health route,
shared schema examples, package boundaries, and validation commands. The first
implementation milestone is the analysis proof described in the BRD; product
choices that still require evidence are recorded in [docs/decisions.md](docs/decisions.md).

## Git workflow

`main` is for approved releases. Ongoing integration happens on `dev`, and
short-lived feature branches start from `dev`.

Never commit customer reports, generated customer files, credentials, or private
evaluation fixtures. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change.
