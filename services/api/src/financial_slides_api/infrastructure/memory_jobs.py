"""Process-local extraction jobs for the database-free demo runtime."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

from financial_slides_api.domain.jobs import (
    Job,
    JobConflictError,
    JobFailure,
    JobStatus,
    StoredSource,
    mark_running,
)


class InMemoryJobStore:
    """Thread-safe job state that is intentionally lost on process restart."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._request_keys: dict[tuple[str, str], str] = {}
        self._sources: dict[str, StoredSource] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def create(self, job: Job) -> Job:
        key = (job.owner_id, job.request_key)
        with self._lock:
            existing_id = self._request_keys.get(key)
            if existing_id:
                existing = self._jobs[existing_id]
                if existing.source_hash == job.source_hash:
                    return existing
                raise JobConflictError("request_key already belongs to different source content")
            self._jobs[job.id] = job
            self._request_keys[key] = job.id
        return job

    def find_by_request_key(self, owner_id: str, request_key: str) -> Job | None:
        with self._lock:
            job_id = self._request_keys.get((owner_id, request_key))
            return self._jobs.get(job_id) if job_id else None

    def get(self, job_id: str, owner_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job if job and job.owner_id == owner_id else None

    def save(self, job: Job) -> Job:
        with self._lock:
            if job.id not in self._jobs:
                raise KeyError(job.id)
            self._jobs[job.id] = job
        return job

    def claim_next(self, now: datetime) -> Job | None:
        with self._lock:
            queued = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.status is JobStatus.QUEUED and job.available_at <= now
                ),
                key=lambda job: (job.available_at, job.created_at),
            )
            if not queued:
                return None
            claimed = mark_running(queued[0], now)
            self._jobs[claimed.id] = claimed
            return claimed

    def recover_stale(self, now: datetime, lease_seconds: float) -> int:
        cutoff = now - timedelta(seconds=lease_seconds)
        recovered = 0
        with self._lock:
            for job in tuple(self._jobs.values()):
                if job.status is not JobStatus.RUNNING or job.updated_at > cutoff:
                    continue
                retryable = job.attempt_count < job.max_attempts
                self._jobs[job.id] = replace(
                    job,
                    status=JobStatus.QUEUED if retryable else JobStatus.FAILED,
                    updated_at=now,
                    available_at=now,
                    finished_at=None if retryable else now,
                    failure=JobFailure(
                        "worker_interrupted",
                        "Worker lease expired; the job was safely requeued."
                        if retryable
                        else "Worker lease expired after the final attempt.",
                    ),
                )
                recovered += 1
        return recovered

    def put_source(self, job_id: str, source: StoredSource) -> None:
        with self._lock:
            self._sources[job_id] = source

    def get_source(self, job_id: str) -> StoredSource:
        with self._lock:
            try:
                return self._sources[job_id]
            except KeyError as error:
                raise KeyError(job_id) from error

    def put_result(self, job_id: str, document: dict[str, Any]) -> None:
        with self._lock:
            self._results[job_id] = deepcopy(document)

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            document = self._results.get(job_id)
            return deepcopy(document) if document is not None else None

    def delete_job_data(self, job_id: str) -> int:
        with self._lock:
            return int(self._sources.pop(job_id, None) is not None) + int(
                self._results.pop(job_id, None) is not None
            )

    def purge_job_data_before(self, cutoff: datetime, now: datetime) -> int:
        deleted = 0
        with self._lock:
            for job in tuple(self._jobs.values()):
                if job.created_at > cutoff:
                    continue
                if job.status not in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                }:
                    self._jobs[job.id] = replace(
                        job,
                        status=JobStatus.CANCELLED,
                        cancel_requested=True,
                        updated_at=now,
                        finished_at=now,
                    )
                deleted += int(self._sources.pop(job.id, None) is not None)
                deleted += int(self._results.pop(job.id, None) is not None)
        return deleted
