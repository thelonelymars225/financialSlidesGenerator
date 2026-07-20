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
  presentation-harness/       Layout selection, fitting, and preflight
  presentation-renderer/      Replaceable PowerPoint renderer adapter
fixtures/
  golden/                      Safe evaluation reports and expected results
docs/                          BRD, architecture, and decision records
```

See [docs/architecture.md](docs/architecture.md) for why these boundaries exist.

## Prerequisites

- Node.js 22 or newer
- pnpm 11 or newer
- Python 3.12 or newer
- uv

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
```

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
