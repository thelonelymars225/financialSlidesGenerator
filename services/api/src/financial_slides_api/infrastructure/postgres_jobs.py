"""PostgreSQL adapter for production job persistence and atomic worker claims."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from financial_slides_api.domain.jobs import (
    Job,
    JobConflictError,
    StoredSource,
    mark_running,
)
from financial_slides_api.infrastructure.job_records import job_to_record, record_to_job

JOB_COLUMNS = """
    id, owner_id, request_key, source_hash, input_mode, file_name,
    declared_media_type, deck_purpose, slide_count, status, created_at,
    updated_at, available_at, started_at, finished_at, attempt_count,
    max_attempts, cancel_requested, failure_code, failure_message,
    route, duration_ms, retries, external_cost_usd
"""

INSERT_JOB_SQL = f"""
    insert into financial_slides.extraction_jobs ({JOB_COLUMNS})
    values (
        %(id)s, %(owner_id)s, %(request_key)s, %(source_hash)s, %(input_mode)s,
        %(file_name)s, %(declared_media_type)s, %(deck_purpose)s, %(slide_count)s,
        %(status)s, %(created_at)s, %(updated_at)s, %(available_at)s,
        %(started_at)s, %(finished_at)s, %(attempt_count)s, %(max_attempts)s,
        %(cancel_requested)s, %(failure_code)s, %(failure_message)s, %(route)s,
        %(duration_ms)s, %(retries)s, %(external_cost_usd)s
    )
"""

UPDATE_JOB_SQL = """
    update financial_slides.extraction_jobs set
        status=%(status)s,
        updated_at=%(updated_at)s,
        available_at=%(available_at)s,
        started_at=%(started_at)s,
        finished_at=%(finished_at)s,
        attempt_count=%(attempt_count)s,
        max_attempts=%(max_attempts)s,
        cancel_requested=%(cancel_requested)s,
        failure_code=%(failure_code)s,
        failure_message=%(failure_message)s,
        route=%(route)s,
        duration_ms=%(duration_ms)s,
        retries=%(retries)s,
        external_cost_usd=%(external_cost_usd)s
    where id=%(id)s
"""

CLAIM_NEXT_SQL = f"""
    select {JOB_COLUMNS}
    from financial_slides.extraction_jobs
    where status = 'queued' and available_at <= %s
    order by available_at, created_at
    for update skip locked
    limit 1
"""


class PostgresJobStore:
    """One server-only adapter implementing every durable extraction-job port."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("database_url is required")
        self.database_url = database_url

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            yield connection

    def create(self, job: Job) -> Job:
        try:
            with self._connection() as connection:
                connection.execute(INSERT_JOB_SQL, job_to_record(job))
            return job
        except UniqueViolation as error:
            existing = self.find_by_request_key(job.owner_id, job.request_key)
            if existing and existing.source_hash == job.source_hash:
                return existing
            raise JobConflictError(
                "request_key already belongs to different source content"
            ) from error

    def find_by_request_key(self, owner_id: str, request_key: str) -> Job | None:
        return self._fetch_one(
            f"""
            select {JOB_COLUMNS}
            from financial_slides.extraction_jobs
            where owner_id = %s and request_key = %s
            """,
            (owner_id, request_key),
        )

    def get(self, job_id: str, owner_id: str) -> Job | None:
        return self._fetch_one(
            f"""
            select {JOB_COLUMNS}
            from financial_slides.extraction_jobs
            where id = %s and owner_id = %s
            """,
            (job_id, owner_id),
        )

    def _fetch_one(self, query: str, params: tuple[Any, ...]) -> Job | None:
        with self._connection() as connection:
            row = connection.execute(query, params).fetchone()
        return record_to_job(row) if row else None

    def save(self, job: Job) -> Job:
        with self._connection() as connection:
            cursor = connection.execute(UPDATE_JOB_SQL, job_to_record(job))
            if cursor.rowcount != 1:
                raise KeyError(job.id)
        return job

    def claim_next(self, now: datetime) -> Job | None:
        with self._connection() as connection:
            row = connection.execute(CLAIM_NEXT_SQL, (now,)).fetchone()
            if row is None:
                return None
            claimed = mark_running(record_to_job(row), now)
            cursor = connection.execute(
                """
                update financial_slides.extraction_jobs set
                    status=%(status)s,
                    updated_at=%(updated_at)s,
                    started_at=%(started_at)s,
                    attempt_count=%(attempt_count)s,
                    failure_code=null,
                    failure_message=null
                where id=%(id)s and status='queued'
                """,
                job_to_record(claimed),
            )
            return claimed if cursor.rowcount == 1 else None

    def recover_stale(self, now: datetime, lease_seconds: float) -> int:
        cutoff = now - timedelta(seconds=lease_seconds)
        with self._connection() as connection:
            retryable = connection.execute(
                """
                update financial_slides.extraction_jobs set
                    status='queued',
                    updated_at=%s,
                    available_at=%s,
                    failure_code='worker_interrupted',
                    failure_message='Worker lease expired; the job was safely requeued.'
                where status='running'
                    and updated_at <= %s
                    and attempt_count < max_attempts
                """,
                (now, now, cutoff),
            ).rowcount
            exhausted = connection.execute(
                """
                update financial_slides.extraction_jobs set
                    status='failed',
                    updated_at=%s,
                    finished_at=%s,
                    failure_code='worker_interrupted',
                    failure_message='Worker lease expired after the final attempt.'
                where status='running'
                    and updated_at <= %s
                    and attempt_count >= max_attempts
                """,
                (now, now, cutoff),
            ).rowcount
        return retryable + exhausted

    def put_source(self, job_id: str, source: StoredSource) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                insert into financial_slides.extraction_sources (
                    job_id, source_text, file_data
                )
                values (%s, %s, %s)
                on conflict (job_id) do update set
                    source_text=excluded.source_text,
                    file_data=excluded.file_data
                """,
                (job_id, source.source_text, source.file_data),
            )

    def get_source(self, job_id: str) -> StoredSource:
        with self._connection() as connection:
            row = connection.execute(
                """
                select j.input_mode, j.file_name, j.declared_media_type,
                       s.source_text, s.file_data
                from financial_slides.extraction_jobs j
                join financial_slides.extraction_sources s on s.job_id = j.id
                where j.id = %s
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return StoredSource(
            input_mode=row["input_mode"],
            source_text=row["source_text"],
            file_name=row["file_name"],
            file_data=bytes(row["file_data"]) if row["file_data"] is not None else None,
            declared_media_type=row["declared_media_type"],
        )

    def put_result(self, job_id: str, document: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                insert into financial_slides.extraction_results (job_id, document_json)
                values (%s, %s)
                on conflict (job_id) do update set document_json=excluded.document_json
                """,
                (job_id, Jsonb(document)),
            )

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                select document_json
                from financial_slides.extraction_results
                where job_id = %s
                """,
                (job_id,),
            ).fetchone()
        return row["document_json"] if row else None
