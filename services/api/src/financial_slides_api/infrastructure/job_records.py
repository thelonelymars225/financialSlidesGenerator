"""Shared conversion between immutable jobs and persistence records."""

from datetime import datetime
from typing import Any, Protocol

from financial_slides_api.domain.jobs import (
    Job,
    JobFailure,
    JobStatus,
    JobTelemetry,
)


class Record(Protocol):
    def __getitem__(self, key: str) -> Any: ...


def _datetime(value: datetime | str | None) -> datetime | None:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def job_to_record(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "owner_id": job.owner_id,
        "request_key": job.request_key,
        "source_hash": job.source_hash,
        "input_mode": job.input_mode,
        "file_name": job.file_name,
        "declared_media_type": job.declared_media_type,
        "deck_purpose": job.deck_purpose,
        "slide_count": job.slide_count,
        "status": job.status.value,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "available_at": job.available_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "cancel_requested": job.cancel_requested,
        "failure_code": job.failure.code if job.failure else None,
        "failure_message": job.failure.message if job.failure else None,
        "route": job.telemetry.route if job.telemetry else None,
        "duration_ms": job.telemetry.duration_ms if job.telemetry else None,
        "retries": job.telemetry.retries if job.telemetry else None,
        "external_cost_usd": job.telemetry.external_cost_usd if job.telemetry else None,
    }


def record_to_job(row: Record) -> Job:
    failure = (
        JobFailure(code=row["failure_code"], message=row["failure_message"])
        if row["failure_code"]
        else None
    )
    telemetry = (
        JobTelemetry(
            route=row["route"],
            duration_ms=float(row["duration_ms"]),
            retries=row["retries"],
            external_cost_usd=float(row["external_cost_usd"]),
        )
        if row["route"]
        else None
    )
    return Job(
        id=str(row["id"]),
        owner_id=row["owner_id"],
        request_key=row["request_key"],
        source_hash=row["source_hash"],
        input_mode=row["input_mode"],
        file_name=row["file_name"],
        declared_media_type=row["declared_media_type"],
        deck_purpose=row["deck_purpose"],
        slide_count=row["slide_count"],
        status=JobStatus(row["status"]),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
        available_at=_datetime(row["available_at"]),
        started_at=_datetime(row["started_at"]),
        finished_at=_datetime(row["finished_at"]),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        cancel_requested=bool(row["cancel_requested"]),
        failure=failure,
        telemetry=telemetry,
    )
