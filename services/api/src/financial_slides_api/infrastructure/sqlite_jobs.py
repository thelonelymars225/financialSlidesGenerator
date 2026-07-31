"""SQLite adapter for durable jobs, queued work, source objects, and results."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from financial_slides_api.domain.jobs import (
    Job,
    JobConflictError,
    JobStatus,
    StoredSource,
    mark_running,
)
from financial_slides_api.infrastructure.job_records import job_to_record, record_to_job


class SQLiteJobStore:
    """One replaceable local adapter implementing all durable job ports.

    The database may live on a cloud persistent volume. Sources are stored as
    bytes/text in the database so a worker never depends on a developer's files.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS extraction_jobs (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    input_mode TEXT NOT NULL,
                    file_name TEXT,
                    declared_media_type TEXT,
                    deck_purpose TEXT NOT NULL,
                    slide_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    attempt_count INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL,
                    failure_code TEXT,
                    failure_message TEXT,
                    route TEXT,
                    duration_ms REAL,
                    retries INTEGER,
                    external_cost_usd REAL,
                    UNIQUE(owner_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS extraction_jobs_queue
                    ON extraction_jobs(status, available_at, created_at);
                CREATE TABLE IF NOT EXISTS extraction_sources (
                    job_id TEXT PRIMARY KEY REFERENCES extraction_jobs(id),
                    source_text TEXT,
                    file_data BLOB
                );
                CREATE TABLE IF NOT EXISTS extraction_results (
                    job_id TEXT PRIMARY KEY REFERENCES extraction_jobs(id),
                    document_json TEXT NOT NULL
                );
                """
            )

    def create(self, job: Job) -> Job:
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO extraction_jobs (
                        id, owner_id, request_key, source_hash, input_mode, file_name,
                        declared_media_type, deck_purpose, slide_count, status, created_at,
                        updated_at, available_at, started_at, finished_at, attempt_count,
                        max_attempts, cancel_requested, failure_code, failure_message,
                        route, duration_ms, retries, external_cost_usd
                    ) VALUES (
                        :id, :owner_id, :request_key, :source_hash, :input_mode, :file_name,
                        :declared_media_type, :deck_purpose, :slide_count, :status, :created_at,
                        :updated_at, :available_at, :started_at, :finished_at, :attempt_count,
                        :max_attempts, :cancel_requested, :failure_code, :failure_message,
                        :route, :duration_ms, :retries, :external_cost_usd
                    )
                    """,
                    job_to_record(job),
                )
            return job
        except sqlite3.IntegrityError as error:
            existing = self.find_by_request_key(job.owner_id, job.request_key)
            if existing and existing.source_hash == job.source_hash:
                return existing
            raise JobConflictError(
                "request_key already belongs to different source content"
            ) from error

    def find_by_request_key(self, owner_id: str, request_key: str) -> Job | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM extraction_jobs WHERE owner_id = ? AND request_key = ?",
                (owner_id, request_key),
            ).fetchone()
        return record_to_job(row) if row else None

    def get(self, job_id: str, owner_id: str) -> Job | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM extraction_jobs WHERE id = ? AND owner_id = ?",
                (job_id, owner_id),
            ).fetchone()
        return record_to_job(row) if row else None

    def save(self, job: Job) -> Job:
        values = job_to_record(job)
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE extraction_jobs SET
                    status=:status, updated_at=:updated_at, available_at=:available_at,
                    started_at=:started_at, finished_at=:finished_at,
                    attempt_count=:attempt_count, max_attempts=:max_attempts,
                    cancel_requested=:cancel_requested, failure_code=:failure_code,
                    failure_message=:failure_message, route=:route,
                    duration_ms=:duration_ms, retries=:retries,
                    external_cost_usd=:external_cost_usd
                WHERE id=:id
                """,
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(job.id)
        return job

    def claim_next(self, now: datetime) -> Job | None:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM extraction_jobs
                WHERE status = ? AND available_at <= ?
                ORDER BY available_at, created_at
                LIMIT 1
                """,
                (JobStatus.QUEUED.value, now.isoformat()),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            claimed = mark_running(record_to_job(row), now)
            values = job_to_record(claimed)
            cursor = connection.execute(
                """
                UPDATE extraction_jobs SET status=:status, updated_at=:updated_at,
                    started_at=:started_at, attempt_count=:attempt_count,
                    failure_code=NULL, failure_message=NULL
                WHERE id=:id AND status='queued'
                """,
                values,
            )
            connection.execute("COMMIT")
            return claimed if cursor.rowcount == 1 else None
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def recover_stale(self, now: datetime, lease_seconds: float) -> int:
        """Requeue interrupted leases or terminally fail exhausted jobs."""
        cutoff = (now - timedelta(seconds=lease_seconds)).isoformat()
        with self._connection() as connection:
            retryable = connection.execute(
                """
                UPDATE extraction_jobs SET
                    status='queued', updated_at=?, available_at=?,
                    failure_code='worker_interrupted',
                    failure_message='Worker lease expired; the job was safely requeued.'
                WHERE status='running' AND updated_at <= ? AND attempt_count < max_attempts
                """,
                (now.isoformat(), now.isoformat(), cutoff),
            ).rowcount
            exhausted = connection.execute(
                """
                UPDATE extraction_jobs SET
                    status='failed', updated_at=?, finished_at=?,
                    failure_code='worker_interrupted',
                    failure_message='Worker lease expired after the final attempt.'
                WHERE status='running' AND updated_at <= ? AND attempt_count >= max_attempts
                """,
                (now.isoformat(), now.isoformat(), cutoff),
            ).rowcount
        return retryable + exhausted

    def put_source(self, job_id: str, source: StoredSource) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO extraction_sources(job_id, source_text, file_data)
                VALUES (?, ?, ?)
                """,
                (job_id, source.source_text, source.file_data),
            )

    def get_source(self, job_id: str) -> StoredSource:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT j.input_mode, j.file_name, j.declared_media_type,
                       s.source_text, s.file_data
                FROM extraction_jobs j
                JOIN extraction_sources s ON s.job_id = j.id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return StoredSource(
            input_mode=row["input_mode"],
            source_text=row["source_text"],
            file_name=row["file_name"],
            file_data=row["file_data"],
            declared_media_type=row["declared_media_type"],
        )

    def put_result(self, job_id: str, document: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO extraction_results(job_id, document_json)
                VALUES (?, ?)
                """,
                (job_id, json.dumps(document, separators=(",", ":"), sort_keys=True)),
            )

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT document_json FROM extraction_results WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return json.loads(row["document_json"]) if row else None

    def delete_job_data(self, job_id: str) -> int:
        """Delete source and extracted output while preserving job metadata."""

        with self._connection() as connection:
            results = connection.execute(
                "DELETE FROM extraction_results WHERE job_id = ?",
                (job_id,),
            ).rowcount
            sources = connection.execute(
                "DELETE FROM extraction_sources WHERE job_id = ?",
                (job_id,),
            ).rowcount
        return results + sources

    def purge_job_data_before(self, cutoff: datetime, now: datetime) -> int:
        """Remove expired content and make unfinished jobs safely terminal."""

        cutoff_iso = cutoff.isoformat()
        now_iso = now.isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE extraction_jobs SET
                    status='cancelled', cancel_requested=1,
                    updated_at=?, finished_at=?
                WHERE created_at <= ?
                    AND status NOT IN ('succeeded', 'failed', 'cancelled')
                """,
                (now_iso, now_iso, cutoff_iso),
            )
            results = connection.execute(
                """
                DELETE FROM extraction_results
                WHERE job_id IN (
                    SELECT id FROM extraction_jobs WHERE created_at <= ?
                )
                """,
                (cutoff_iso,),
            ).rowcount
            sources = connection.execute(
                """
                DELETE FROM extraction_sources
                WHERE job_id IN (
                    SELECT id FROM extraction_jobs WHERE created_at <= ?
                )
                """,
                (cutoff_iso,),
            ).rowcount
        return results + sources
