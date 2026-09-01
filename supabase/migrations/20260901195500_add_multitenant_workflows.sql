create table if not exists financial_slides.organizations (
    id uuid primary key default gen_random_uuid(),
    name text not null check (length(name) between 1 and 120),
    region text not null default 'eu-central-1'
        check (region = 'eu-central-1'),
    hosted_ai_enabled boolean not null default false,
    source_retention_hours integer not null default 24
        check (source_retention_hours between 1 and 8760),
    artifact_retention_hours integer not null default 24
        check (artifact_retention_hours between 1 and 8760),
    created_by uuid not null references auth.users (id) on delete restrict,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists financial_slides.organization_memberships (
    organization_id uuid not null
        references financial_slides.organizations (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    role text not null check (role in ('owner', 'admin', 'member')),
    created_at timestamptz not null default now(),
    primary key (organization_id, user_id)
);

alter table financial_slides.extraction_jobs
    add column if not exists organization_id uuid
        references financial_slides.organizations (id) on delete restrict,
    add column if not exists created_by uuid
        references auth.users (id) on delete set null,
    add column if not exists state_version bigint not null default 0
        check (state_version >= 0);

create index if not exists extraction_jobs_organization_created_idx
    on financial_slides.extraction_jobs (organization_id, created_at desc);

create table if not exists financial_slides.uploads (
    id uuid primary key,
    organization_id uuid not null
        references financial_slides.organizations (id) on delete cascade,
    created_by uuid not null references auth.users (id) on delete restrict,
    object_key text not null unique,
    file_name text not null,
    media_type text not null check (media_type = 'application/pdf'),
    size_bytes bigint not null check (size_bytes between 1 and 26214400),
    sha256 text not null check (sha256 ~ '^sha256:[0-9a-f]{64}$'),
    status text not null check (
        status in ('pending', 'uploaded', 'scanning', 'ready', 'rejected', 'deleted')
    ),
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    expires_at timestamptz not null
);

create table if not exists financial_slides.workflow_attempts (
    id uuid primary key,
    organization_id uuid not null
        references financial_slides.organizations (id) on delete cascade,
    job_id uuid not null references financial_slides.extraction_jobs (id) on delete cascade,
    workflow_type text not null check (workflow_type in ('extraction', 'generation', 'deletion')),
    attempt integer not null check (attempt > 0),
    temporal_workflow_id text not null,
    temporal_run_id text,
    status text not null check (
        status in ('pending', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (job_id, workflow_type, attempt),
    unique (temporal_workflow_id)
);

create table if not exists financial_slides.workflow_events (
    id bigint generated always as identity primary key,
    organization_id uuid not null
        references financial_slides.organizations (id) on delete cascade,
    job_id uuid not null references financial_slides.extraction_jobs (id) on delete cascade,
    attempt_id uuid references financial_slides.workflow_attempts (id) on delete cascade,
    stage text not null,
    event_type text not null,
    progress integer not null check (progress between 0 and 100),
    failure_code text,
    created_at timestamptz not null default now()
);

create index if not exists workflow_events_job_created_idx
    on financial_slides.workflow_events (job_id, created_at, id);

create table if not exists financial_slides.workflow_outbox (
    id uuid primary key,
    organization_id uuid not null
        references financial_slides.organizations (id) on delete cascade,
    aggregate_id uuid not null,
    event_type text not null,
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    created_at timestamptz not null default now(),
    claimed_at timestamptz,
    delivered_at timestamptz,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    last_error_code text
);

create index if not exists workflow_outbox_pending_idx
    on financial_slides.workflow_outbox (created_at)
    where delivered_at is null;

create table if not exists financial_slides.audit_events (
    id bigint generated always as identity primary key,
    organization_id uuid references financial_slides.organizations (id) on delete set null,
    actor_id uuid references auth.users (id) on delete set null,
    action text not null,
    resource_type text not null,
    resource_id uuid,
    outcome text not null check (outcome in ('allowed', 'denied', 'failed')),
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now()
);

create table if not exists financial_slides.organization_usage (
    organization_id uuid not null
        references financial_slides.organizations (id) on delete cascade,
    quota_name text not null check (quota_name in ('job_submissions', 'hosted_ai_calls')),
    bucket_started_at timestamptz not null,
    used integer not null default 0 check (used >= 0),
    primary key (organization_id, quota_name, bucket_started_at)
);

create or replace function financial_slides.consume_hourly_quota(
    requested_organization_id uuid,
    requested_quota_name text,
    requested_limit integer
) returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    consumed boolean;
begin
    if requested_limit < 1 or requested_quota_name not in ('job_submissions', 'hosted_ai_calls') then
        raise exception 'invalid quota request';
    end if;
    insert into financial_slides.organization_usage (
        organization_id, quota_name, bucket_started_at, used
    ) values (
        requested_organization_id,
        requested_quota_name,
        date_trunc('hour', now()),
        1
    )
    on conflict (organization_id, quota_name, bucket_started_at)
    do update set used = financial_slides.organization_usage.used + 1
    where financial_slides.organization_usage.used < requested_limit
    returning true into consumed;
    return coalesce(consumed, false);
end;
$$;

alter table financial_slides.organizations enable row level security;
alter table financial_slides.organization_memberships enable row level security;
alter table financial_slides.uploads enable row level security;
alter table financial_slides.workflow_attempts enable row level security;
alter table financial_slides.workflow_events enable row level security;
alter table financial_slides.workflow_outbox enable row level security;
alter table financial_slides.audit_events enable row level security;
alter table financial_slides.organization_usage enable row level security;

alter table financial_slides.organizations force row level security;
alter table financial_slides.organization_memberships force row level security;
alter table financial_slides.extraction_jobs force row level security;
alter table financial_slides.extraction_sources force row level security;
alter table financial_slides.extraction_results force row level security;
alter table financial_slides.uploads force row level security;
alter table financial_slides.workflow_attempts force row level security;
alter table financial_slides.workflow_events force row level security;
alter table financial_slides.workflow_outbox force row level security;
alter table financial_slides.audit_events force row level security;
alter table financial_slides.organization_usage force row level security;

revoke all on financial_slides.organizations from public, anon, authenticated;
revoke all on financial_slides.organization_memberships from public, anon, authenticated;
revoke all on financial_slides.uploads from public, anon, authenticated;
revoke all on financial_slides.workflow_attempts from public, anon, authenticated;
revoke all on financial_slides.workflow_events from public, anon, authenticated;
revoke all on financial_slides.workflow_outbox from public, anon, authenticated;
revoke all on financial_slides.audit_events from public, anon, authenticated;
revoke all on financial_slides.organization_usage from public, anon, authenticated;
revoke all on function financial_slides.consume_hourly_quota(uuid, text, integer)
    from public, anon, authenticated;

grant select, insert, update, delete on
    financial_slides.organizations,
    financial_slides.organization_memberships,
    financial_slides.uploads,
    financial_slides.workflow_attempts,
    financial_slides.workflow_events,
    financial_slides.workflow_outbox,
    financial_slides.audit_events
    ,financial_slides.organization_usage
to service_role;

grant execute on function financial_slides.consume_hourly_quota(uuid, text, integer)
    to service_role;

grant usage, select on all sequences in schema financial_slides to service_role;

create policy "deny direct client access"
    on financial_slides.organizations for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.organization_memberships for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.uploads for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.workflow_attempts for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.workflow_events for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.workflow_outbox for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.audit_events for all to anon, authenticated
    using (false) with check (false);
create policy "deny direct client access"
    on financial_slides.organization_usage for all to anon, authenticated
    using (false) with check (false);
