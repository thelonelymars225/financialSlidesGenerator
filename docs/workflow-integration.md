# Durable workflow integration

Production uses PostgreSQL as the source of truth and Temporal Cloud as the
orchestrator. Set `WORKFLOW_BACKEND=temporal` on both API and worker. Startup
fails closed unless PostgreSQL and the Temporal address, namespace, and API key
are present.

## Submission sequence

1. The API verifies the Supabase JWT and organization membership.
2. It consumes the organization's hourly quota.
3. For files, the browser uploads to private Supabase Storage with a signed URL;
   the API verifies size, hash, and file signature.
4. One PostgreSQL transaction creates the extraction job, source record, and
   `extraction.requested` outbox event.
5. The worker claims outbox rows with `FOR UPDATE SKIP LOCKED`, starts the
   deterministic Temporal workflow ID `extract:<organization>:<job>`, and marks
   the event delivered. A repeated start is treated as success.
6. The Temporal activity atomically claims that exact job, executes extraction,
   and writes a version-checked terminal state. Retries are bounded at both the
   workflow and domain layers.

Run the worker with:

```bash
python -m financial_slides_api.temporal_worker
```

Temporal should use an EU namespace colocated with Supabase `eu-central-1`.
Create separate task queues and credentials for extraction and future hosted-AI
activities so a compromised parser worker cannot access model or presentation
secrets. No report text or bytes belong in workflow arguments, search
attributes, logs, or error messages.

## Rollout

Apply migrations first, deploy the Temporal worker with polling disabled at the
platform level, deploy the API, then enable both worker replicas. Watch oldest
undelivered outbox age, dispatch failures, workflow failure rate, queue latency,
and job state-version conflicts. Roll back by setting `WORKFLOW_BACKEND=local`
only for non-production/local operation; production validation intentionally
requires the durable configuration.
