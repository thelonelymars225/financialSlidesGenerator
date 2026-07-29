"""Application orchestration for durable asynchronous extraction jobs."""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from financial_slides_api.domain.jobs import (
    CreateJobCommand,
    Job,
    JobConflictError,
    JobNotFoundError,
    JobNotReadyError,
    JobStatus,
    JobTelemetry,
    StoredSource,
    request_cancel,
)
from financial_slides_api.infrastructure.audit import MetadataAuditLogger, NullAuditSink
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.ports.jobs import JobRepository, JobStore, ResultStore, SourceStore
from financial_slides_api.ports.privacy import AuditSink, RetentionStore
from financial_slides_api.services.privacy import RetentionPolicy, get_retention_policy


def source_bytes(command: CreateJobCommand) -> bytes:
    if command.input_mode == "text":
        return (command.source_text or "").encode("utf-8")
    return command.file_data or b""


def source_hash(command: CreateJobCommand) -> str:
    return f"sha256:{sha256(source_bytes(command)).hexdigest()}"


def default_request_key(command: CreateJobCommand, digest: str) -> str:
    identity = (
        f"{command.owner_id}\0{digest}\0{command.deck_purpose}\0{command.slide_count}"
    ).encode()
    return f"source:{sha256(identity).hexdigest()}"


class ExtractionJobService:
    def __init__(
        self,
        repository: JobRepository,
        sources: SourceStore,
        results: ResultStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_attempts: int = 3,
        retention: RetentionStore | None = None,
        policy: RetentionPolicy = RetentionPolicy(),
        audit: AuditSink | None = None,
    ) -> None:
        self._repository = repository
        self._sources = sources
        self._results = results
        self._clock = clock
        self._max_attempts = max_attempts
        self._retention = retention
        self._policy = policy
        self._audit = audit or NullAuditSink()

    def create(self, command: CreateJobCommand) -> Job:
        self.purge_expired()
        digest = source_hash(command)
        request_key = command.request_key or default_request_key(command, digest)
        existing = self._repository.find_by_request_key(command.owner_id, request_key)
        if existing:
            if existing.source_hash != digest:
                raise JobConflictError("request_key already belongs to different source content")
            return existing

        now = self._clock()
        job = Job(
            id=str(uuid4()),
            owner_id=command.owner_id,
            request_key=request_key,
            source_hash=digest,
            input_mode=command.input_mode,
            file_name=command.file_name,
            declared_media_type=command.declared_media_type,
            deck_purpose=command.deck_purpose,
            slide_count=command.slide_count,
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
            available_at=now,
            max_attempts=self._max_attempts,
        )
        job = self._repository.create(job)
        self._sources.put_source(
            job.id,
            StoredSource(
                input_mode=command.input_mode,
                source_text=command.source_text,
                file_name=command.file_name,
                file_data=command.file_data,
                declared_media_type=command.declared_media_type,
            ),
        )
        return job

    def get(self, job_id: str, owner_id: str) -> Job:
        self.purge_expired()
        job = self._repository.get(job_id, owner_id)
        if job is None:
            raise JobNotFoundError("job was not found")
        return job

    def result(self, job_id: str, owner_id: str) -> tuple[Job, dict]:
        job = self.get(job_id, owner_id)
        if job.status is not JobStatus.SUCCEEDED:
            raise JobNotReadyError(f"job is {job.status.value}; result is not available")
        document = self._results.get_result(job.id)
        if document is None:
            raise JobNotReadyError("job result is not available")
        return job, document

    def cancel(self, job_id: str, owner_id: str) -> Job:
        job = self.get(job_id, owner_id)
        cancelled = request_cancel(job, self._clock())
        return self._repository.save(cancelled) if cancelled is not job else job

    def delete_data(self, job_id: str, owner_id: str) -> int:
        if self._retention is None:
            raise RuntimeError("source-data deletion is not configured")
        job = self.get(job_id, owner_id)
        now = self._clock()
        cancelled = request_cancel(job, now)
        if cancelled is not job:
            self._repository.save(cancelled)
        deleted = self._retention.delete_job_data(job.id)
        self._audit.record(
            "source_data_deleted",
            job.id,
            owner_id,
            deleted_count=deleted,
        )
        return deleted

    def purge_expired(self) -> int:
        if self._retention is None:
            return 0
        now = self._clock()
        deleted = self._retention.purge_job_data_before(
            self._policy.source_cutoff(now),
            now,
        )
        if deleted:
            self._audit.record(
                "source_data_expired",
                "retention-batch",
                None,
                deleted_count=deleted,
            )
        return deleted


def configured_job_store() -> JobStore:
    database_url = os.getenv("DATABASE_URL", "")
    adapter = os.getenv("FINANCIAL_SLIDES_STORE") or ("postgres" if database_url else "sqlite")
    if adapter == "sqlite":
        configured = os.getenv("FINANCIAL_SLIDES_JOB_DB", ".data/extraction-jobs.sqlite3")
        return SQLiteJobStore(Path(configured))
    if adapter == "postgres":
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for the postgres job store")
        from financial_slides_api.infrastructure.postgres_jobs import PostgresJobStore

        return PostgresJobStore(database_url)
    raise RuntimeError(f"unsupported FINANCIAL_SLIDES_STORE: {adapter}")


@lru_cache(maxsize=1)
def get_job_store() -> JobStore:
    return configured_job_store()


@lru_cache(maxsize=1)
def get_job_service() -> ExtractionJobService:
    store = get_job_store()
    return ExtractionJobService(
        store,
        store,
        store,
        retention=store,
        policy=get_retention_policy(),
        audit=MetadataAuditLogger(),
    )


def telemetry_from_extraction(result, attempts: int) -> JobTelemetry:
    return JobTelemetry(
        route=result.telemetry.route,
        duration_ms=result.telemetry.duration_ms,
        retries=max(0, attempts - 1),
        external_cost_usd=result.telemetry.external_cost_usd,
    )
