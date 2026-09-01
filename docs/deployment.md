# Production deployment

The production topology has a Cloudflare Pages frontend, a private-to-database
FastAPI service, a Temporal worker, Supabase Auth/PostgreSQL/Storage in Frankfurt
(`eu-central-1`), and a Temporal Cloud EU namespace. The local memory/SQLite
profile is for development only.

## Order of operations

1. Create the Supabase project in Frankfurt and apply all files in
   `supabase/migrations` with the Supabase CLI.
2. Create a Temporal Cloud EU namespace and separate API key for the worker.
3. Deploy the API from `Dockerfile.api` and worker from `Dockerfile.worker`.
4. Deploy `apps/web` to Cloudflare Pages and set the API's exact Pages/custom
   domain in `CORS_ALLOWED_ORIGINS`.
5. Run authenticated smoke tests for two organizations, including an attempted
   cross-tenant read, signed upload, cancellation, deletion, and quota response.

## API and worker configuration

Store these as platform secrets, never frontend variables:

```dotenv
APP_ENV=production
AUTH_REQUIRED=true
FINANCIAL_SLIDES_STORE=postgres
DATABASE_URL=postgresql://...?sslmode=require
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SECRET_KEY=...
SUPABASE_JWT_AUDIENCE=authenticated
WORKFLOW_BACKEND=temporal
TEMPORAL_ADDRESS=<namespace>.<region>.tmprl.cloud:7233
TEMPORAL_NAMESPACE=<namespace>.<account>
TEMPORAL_API_KEY=...
TEMPORAL_TASK_QUEUE=financial-slides-extraction-v1
CORS_ALLOWED_ORIGINS=https://<pages-domain>,https://<custom-domain>
API_MAX_BODY_BYTES=3145728
JOB_SUBMISSIONS_PER_ORG_HOUR=60
FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS=24
FINANCIAL_SLIDES_ARTIFACT_RETENTION_HOURS=24
```

If the model provider is enabled, also configure its server-only credentials and
`MODEL_DATA_RETENTION_DISABLED=true`. Each tenant must separately opt in through
`organizations.hosted_ai_enabled`; the worker otherwise refuses hosted analysis.

Only set `FORWARDED_ALLOW_IPS` to the documented proxy CIDRs for the deployment
platform. The image defaults to loopback and does not trust arbitrary forwarded
headers.

## Frontend configuration

These are intentionally public build values:

```dotenv
VITE_API_BASE_URL=https://<api-domain>
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
```

The application stores only the chosen organization ID locally. Supabase stores
and refreshes its browser session; API calls send the access token and selected
organization, and the server always rechecks membership.

## Release checks

Run the monorepo test/build workflow, CodeQL, dependency review, `pnpm audit`,
`pip-audit`, Supabase database lint/advisors, and both container builds. Confirm
the `/health` route, CSP/security headers, private bucket status, outbox lag,
Temporal worker pollers, and alert routing. Restore a database backup in a test
project before the first customer release and at least quarterly thereafter.
