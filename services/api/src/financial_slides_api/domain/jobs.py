"""Immutable extraction-job domain models and deterministic state rules."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})


@dataclass(frozen=True)
class JobFailure:
    code: str
    message: str


@dataclass(frozen=True)
class JobTelemetry:
    route: str
    duration_ms: float
    retries: int
    external_cost_usd: float


@dataclass(frozen=True)
class Job:
    id: str
    owner_id: str
    request_key: str
    source_hash: str
    input_mode: str
    file_name: str | None
    declared_media_type: str | None
    deck_purpose: str
    slide_count: int
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    available_at: datetime
    organization_id: str | None = None
    created_by: str | None = None
    state_version: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    cancel_requested: bool = False
    failure: JobFailure | None = None
    telemetry: JobTelemetry | None = None


@dataclass(frozen=True)
class CreateJobCommand:
    owner_id: str
    input_mode: str
    source_text: str | None
    file_name: str | None
    file_data: bytes | None
    declared_media_type: str | None
    deck_purpose: str
    slide_count: int
    request_key: str | None = None
    organization_id: str | None = None
    created_by: str | None = None


@dataclass(frozen=True)
class StoredSource:
    input_mode: str
    source_text: str | None
    file_name: str | None
    file_data: bytes | None
    declared_media_type: str | None


class JobError(Exception):
    """Base typed job-domain failure."""


class JobConflictError(JobError):
    """An idempotency key was reused for different source content."""


class JobNotFoundError(JobError):
    """The job does not exist or is not visible to the caller."""


class JobNotReadyError(JobError):
    """The caller requested a result before successful completion."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def request_cancel(job: Job, now: datetime) -> Job:
    if job.status in TERMINAL_STATUSES:
        return job
    return replace(
        job,
        status=JobStatus.CANCELLED,
        cancel_requested=True,
        updated_at=now,
        finished_at=now,
    )


def mark_running(job: Job, now: datetime) -> Job:
    if job.status is not JobStatus.QUEUED:
        raise ValueError(f"cannot start a {job.status} job")
    return replace(
        job,
        status=JobStatus.RUNNING,
        started_at=job.started_at or now,
        updated_at=now,
        attempt_count=job.attempt_count + 1,
        failure=None,
    )


def mark_succeeded(job: Job, telemetry: JobTelemetry, now: datetime) -> Job:
    if job.status is not JobStatus.RUNNING:
        raise ValueError(f"cannot succeed a {job.status} job")
    return replace(
        job,
        status=JobStatus.SUCCEEDED,
        updated_at=now,
        finished_at=now,
        failure=None,
        telemetry=telemetry,
    )


def retry_or_fail(
    job: Job,
    failure: JobFailure,
    *,
    retryable: bool,
    retry_delay_seconds: float,
    now: datetime,
) -> Job:
    if job.status is not JobStatus.RUNNING:
        raise ValueError(f"cannot fail a {job.status} job")
    should_retry = retryable and job.attempt_count < job.max_attempts
    if should_retry:
        from datetime import timedelta

        return replace(
            job,
            status=JobStatus.QUEUED,
            updated_at=now,
            available_at=now + timedelta(seconds=retry_delay_seconds),
            failure=failure,
        )
    return replace(
        job,
        status=JobStatus.FAILED,
        updated_at=now,
        finished_at=now,
        failure=failure,
    )


def telemetry_dict(telemetry: JobTelemetry | None) -> dict[str, Any] | None:
    if telemetry is None:
        return None
    return {
        "route": telemetry.route,
        "duration_ms": telemetry.duration_ms,
        "retries": telemetry.retries,
        "external_cost_usd": telemetry.external_cost_usd,
    }
