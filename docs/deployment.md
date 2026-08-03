# Cloud deployment

The demo deploys as two services from one repository:

- Cloudflare Pages builds `apps/web`.
- Railway runs the self-contained FastAPI service using `Dockerfile.api`.
- Extraction is scheduled as an in-process background task after submission.

The demo runtime keeps extraction and generation jobs in memory. It has no
Supabase/PostgreSQL dependency, and its jobs disappear whenever Railway restarts
or redeploys. Restore a durable adapter before using this with customer data.

## Railway

Create one Railway service sourced from this GitHub repository and the release
branch. Leave the root directory at `/` because the
Python packages and Node presentation packages share root lockfiles.

| Service | Config file | Public domain |
| --- | --- | --- |
| `financial-slides-api` | `/deploy/railway-api.toml` | Generate one |
Do not set `DATABASE_URL`, `SUPABASE_URL`, or `SUPABASE_SECRET_KEY` for this
runtime. Remove `FINANCIAL_SLIDES_STORE`, or set it to `memory` explicitly.

```dotenv
APP_ENV=production
FINANCIAL_SLIDES_STORE=memory
FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS=24
FINANCIAL_SLIDES_ARTIFACT_RETENTION_HOURS=24
```

Set the hosted-model variables on the API service:

```dotenv
MODEL_PROVIDER=deepseek
MODEL_API_KEY=<server-only provider key>
MODEL_DATA_RETENTION_DISABLED=true
```

The separate Railway worker service and Supabase variables are intentionally
unused in this demo profile.

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
3. Confirm the in-process worker changes the extraction job from queued to succeeded.
4. Generate and download a PowerPoint file.
5. Delete the test source and generated artifact.
