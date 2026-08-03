# Cloud deployment

The monorepo deploys as three independent processes without copying source code:

- Cloudflare Pages builds `apps/web`.
- Railway runs the FastAPI service using `Dockerfile.api`.
- Railway runs the continuous extraction worker using `Dockerfile.worker`.
- Both Railway services use the existing Supabase database and private buckets.

## Railway

Create an empty Railway project, then add two services sourced from this GitHub
repository and the release branch. Leave the root directory at `/` because the
Python packages and Node presentation packages share root lockfiles.

| Service | Config file | Public domain |
| --- | --- | --- |
| `financial-slides-api` | `/deploy/railway-api.toml` | Generate one |
| `financial-slides-worker` | `/deploy/railway-worker.toml` | None |

Share the persistence variables between both services:

```dotenv
APP_ENV=production
FINANCIAL_SLIDES_STORE=postgres
DATABASE_URL=<Supabase session-pooler connection string>
SUPABASE_URL=<project URL>
SUPABASE_SECRET_KEY=<server-only secret key>
SUPABASE_SOURCE_BUCKET=source-documents
SUPABASE_PRESENTATION_BUCKET=generated-presentations
FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS=24
FINANCIAL_SLIDES_ARTIFACT_RETENTION_HOURS=24
```

Set the hosted-model variables on the API service only. The extraction worker
does not call the analysis model:

```dotenv
MODEL_PROVIDER=deepseek
MODEL_API_KEY=<server-only provider key>
MODEL_DATA_RETENTION_DISABLED=true
```

Use the Supabase session pooler on port 5432 unless the Railway deployment is
confirmed to reach the direct IPv6 endpoint. Never commit these values or copy
`SUPABASE_SECRET_KEY` into the frontend service.

## Cloudflare Pages

Create one Pages project from the same repository with these build settings:

| Setting | Value |
| --- | --- |
| Root directory | `/` |
| Build command | `corepack enable && pnpm install --frozen-lockfile && pnpm --filter @financial-slides/web build` |
| Build output directory | `apps/web/dist` |
| Node version | `.node-version` |
| Build variable | `VITE_API_BASE_URL=https://<api-domain>.up.railway.app` |

After Cloudflare assigns the Pages domain, set the API service variable
`CORS_ALLOWED_ORIGINS` to that exact `https://...pages.dev` origin. Add the
custom domain later as a second comma-separated origin.

For an initial private demo, deploy `dev`. Before a customer-facing release,
promote the tested commit to `main`, add authentication-derived owner IDs, and
persist generation jobs and presentation artifacts outside API process memory.

## Smoke test

1. Confirm `GET https://<api-domain>/health` returns HTTP 200.
2. Open the Pages URL and submit safe pasted text.
3. Confirm the worker changes the extraction job from queued to succeeded.
4. Generate and download a PowerPoint file.
5. Restart the worker and confirm a new job is still processed.
6. Delete the test source and generated artifact.
