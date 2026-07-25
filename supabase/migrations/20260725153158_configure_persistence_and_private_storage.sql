create schema if not exists financial_slides;

revoke all on schema financial_slides from public, anon, authenticated;
grant usage on schema financial_slides to service_role;

create table if not exists financial_slides.extraction_jobs (
    id uuid primary key,
    owner_id text not null,
    request_key text not null,
    source_hash text not null,
    input_mode text not null check (input_mode in ('text', 'file')),
    file_name text,
    declared_media_type text,
    deck_purpose text not null,
    slide_count integer not null check (slide_count between 1 and 100),
    status text not null check (
        status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    created_at timestamptz not null,
    updated_at timestamptz not null,
    available_at timestamptz not null,
    started_at timestamptz,
    finished_at timestamptz,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    max_attempts integer not null default 3 check (max_attempts > 0),
    cancel_requested boolean not null default false,
    failure_code text,
    failure_message text,
    route text,
    duration_ms double precision check (duration_ms is null or duration_ms >= 0),
    retries integer check (retries is null or retries >= 0),
    external_cost_usd numeric(14, 8) check (
        external_cost_usd is null or external_cost_usd >= 0
    ),
    unique (owner_id, request_key)
);

create index if not exists extraction_jobs_available_queue_idx
    on financial_slides.extraction_jobs (available_at, created_at)
    where status = 'queued';

create index if not exists extraction_jobs_running_lease_idx
    on financial_slides.extraction_jobs (updated_at)
    where status = 'running';

create table if not exists financial_slides.extraction_sources (
    job_id uuid primary key
        references financial_slides.extraction_jobs (id) on delete cascade,
    source_text text,
    file_data bytea,
    check (source_text is not null or file_data is not null)
);

create table if not exists financial_slides.extraction_results (
    job_id uuid primary key
        references financial_slides.extraction_jobs (id) on delete cascade,
    document_json jsonb not null
);

alter table financial_slides.extraction_jobs enable row level security;
alter table financial_slides.extraction_sources enable row level security;
alter table financial_slides.extraction_results enable row level security;

revoke all on all tables in schema financial_slides from public, anon, authenticated;
grant select, insert, update, delete
    on all tables in schema financial_slides
    to service_role;

alter default privileges in schema financial_slides
    revoke all on tables from public, anon, authenticated;
alter default privileges in schema financial_slides
    grant select, insert, update, delete on tables to service_role;

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values
    (
        'source-documents',
        'source-documents',
        false,
        26214400,
        array[
            'application/pdf',
            'text/plain',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        ]
    ),
    (
        'generated-presentations',
        'generated-presentations',
        false,
        52428800,
        array[
            'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        ]
    )
on conflict (id) do update
set
    name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
