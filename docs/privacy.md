# Privacy, retention, and deletion

The MVP minimizes how long financial source content and generated presentation
data remain available. These controls are application safeguards, not a claim
of production compliance.

## Defaults and configuration

Source files, pasted text, extracted documents, slide specifications, and
PowerPoint artifacts default to 24 hours of retention. Operators may configure
one to 8,760 hours:

```dotenv
FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS=24
FINANCIAL_SLIDES_ARTIFACT_RETENTION_HOURS=24
```

Retention cleanup runs lazily during API traffic. This makes the control work in
the secretless local baseline without a scheduler. A production deployment
should also invoke the same cleanup from a scheduled worker so expiry is not
dependent on traffic. Job metadata remains after content deletion to preserve
idempotency, failure diagnostics, and a minimal audit trail.

## User deletion

Both deletion endpoints require the same owner identity used to create the job:

- `DELETE /api/jobs/{job_id}/data` deletes uploaded/pasted source data and the
  extracted-document result. An unfinished extraction is cancelled first.
- `DELETE /api/slide-jobs/{job_id}/output` deletes the slide specification and
  PowerPoint bytes. Running generation cannot be deleted until it is terminal.

The operations are idempotent. A different owner receives `404` rather than
learning whether the resource exists. After source data is deleted or expires,
submit a new request key to process the same document again.

## Logging and provider data use

Privacy audit events contain only the action, internal resource ID, a truncated
hash of the owner ID, and deletion count. Source text, filenames, extracted
content, model prompts, model responses, artifact bytes, and secrets are not
logged by these controls.

Hosted analysis is disabled unless the operator sets:

```dotenv
MODEL_DATA_RETENTION_DISABLED=true
```

This is an operator assertion, not an API-side provider configuration change.
Verify the provider account's data-use and retention settings before enabling
it. The deterministic local analysis path does not require the assertion.

## Storage and access boundaries

- Supabase application tables use a private schema with row-level security and
  no anonymous or authenticated grants. Object buckets are private.
- Supabase connections use TLS and the managed service provides encryption at
  rest. The local SQLite fallback relies on host volume and filesystem controls;
  it does not add database-level encryption.
- `SUPABASE_SECRET_KEY`, database credentials, and model keys stay server-side
  and must never be exposed to the web client or committed.
- `X-Owner-ID` is a development isolation boundary, not authentication. Before
  external production use, replace it with a verified identity from the
  authentication layer and derive ownership server-side.
- These audit events are local structured logs. Durable, access-controlled,
  tamper-resistant audit storage remains deployment infrastructure work.

Tests cover retention parsing, owner isolation, manual deletion, lazy expiry,
metadata-only logging, private Supabase storage definitions, and refusal to
enable a hosted provider without the retention assertion.
