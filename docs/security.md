# Security model

The production boundary is tenant-first: every authenticated request carries a
Supabase access token and an explicit organization UUID. The API verifies the
token against the project's asymmetric JWKS, validates issuer, audience,
expiry, subject, and signing algorithm, then resolves membership from the
private `financial_slides.organization_memberships` table. A caller-supplied
`X-Owner-ID` is accepted only in local development and is rejected when
authentication is required.

## Controls implemented

- Organizations have `owner`, `admin`, and `member` roles. Destructive source
  and artifact deletion requires an owner or admin.
- Private application tables deny `anon` and `authenticated` roles. Only the
  server-side service role connects to them, with RLS forced as defense in depth.
- Job writes use an optimistic `state_version`; queue claims use row locking and
  `SKIP LOCKED` to prevent duplicate or lost transitions.
- Per-organization submission quotas are consumed atomically in PostgreSQL.
- Browser uploads use a two-hour signed URL to a private bucket. The API verifies
  the byte count, SHA-256 digest, and PDF signature before creating a job.
- Source and artifact retention defaults are 24 hours. Deletion preserves
  metadata-only audit records and removes report content.
- Hosted analysis is denied unless `organizations.hosted_ai_enabled` is true and
  the operator has asserted that provider retention is disabled.
- Temporal payloads contain only organization and job IDs. Source data remains
  in private storage/database records.
- The API limits request bodies, uses exact CORS origins, disables credentialed
  CORS, and returns no-store and browser hardening headers. Cloudflare Pages
  applies a restrictive CSP and immutable caching only to fingerprinted assets.
- Runtime images are non-root and copy allowlisted files. `.dockerignore`
  excludes local secrets, customer fixtures, VCS metadata, and generated data.

Two `image-size` denial-of-service advisories currently have no patched npm
release. They are explicitly recorded in `pnpm-workspace.yaml`; the affected
ICNS/JXL/HEIF parsers are unreachable because the only customer file contract is
a size/hash/signature-verified PDF. Remove the temporary audit exception as soon
as a patched upstream version is published.

## Secret handling

`SUPABASE_SECRET_KEY`, `DATABASE_URL`, `TEMPORAL_API_KEY`, and model credentials
are server-only deployment secrets. Never prefix them with `VITE_`; only the
Supabase URL and publishable browser key are public build variables. Rotate a
secret after suspected disclosure, review `audit_events`, and redeploy API and
worker services.

## Residual operational work

Before production, provision the Supabase and Temporal namespaces in Frankfurt,
enable PITR and log drains, configure alerting for outbox age/failures, quota
rejections, auth denials, and worker failures, and test restore plus secret
rotation. Run a third-party penetration test before storing customer reports.
