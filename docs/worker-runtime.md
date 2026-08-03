# Extraction worker runtime

> The current Railway demo does not use this separate durable-worker profile.
> The API schedules extraction in-process and uses memory-only state. Keep this
> document for the later return to restart-safe persistence.

The API only validates and enqueues extraction jobs. A separate worker process
must use the same durable job store and continuously claim queued work.

## Cloud process

Run one or more worker instances with:

```bash
uv run --package financial-slides-api python -m financial_slides_api.worker \
  --watch \
  --limit 4 \
  --poll-interval-seconds 1 \
  --error-backoff-seconds 5
```

Set `DATABASE_URL` for both the API and worker to use the same PostgreSQL
database. Without `DATABASE_URL`, both processes must share the SQLite file
selected by `FINANCIAL_SLIDES_JOB_DB`; SQLite is intended only for local or
single-host operation.

The watch loop immediately requests another bounded batch after processing
work, waits between empty polls, backs off after a transient batch failure, and
stops cleanly on `SIGINT` or `SIGTERM`. Atomic database claims retain the
existing protection against duplicate processing when multiple workers run.

The process manager should restart a worker that exits unexpectedly. Provider
keys and database credentials remain server-side environment variables.

For the current memory-only demo, `pnpm dev` starts the API and web application;
the API processes extraction in the background. `pnpm dev:worker` remains
available only for an explicitly configured durable store.

## One-shot operation

Development and cron-style bounded runs remain available:

```bash
uv run --package financial-slides-api python -m financial_slides_api.worker --limit 4
```

The one-shot command processes at most the requested batch and exits.
