"""Protocols for durable job state, queued work, source objects, and results."""

from datetime import datetime
from typing import Any, Protocol

from financial_slides_api.domain.jobs import Job, StoredSource


class JobRepository(Protocol):
    def create(self, job: Job) -> Job: ...

    def find_by_request_key(self, owner_id: str, request_key: str) -> Job | None: ...

    def get(self, job_id: str, owner_id: str) -> Job | None: ...

    def save(self, job: Job) -> Job: ...


class JobQueue(Protocol):
    def claim_next(self, now: datetime) -> Job | None: ...

    def recover_stale(self, now: datetime, lease_seconds: float) -> int: ...


class SourceStore(Protocol):
    def put_source(self, job_id: str, source: StoredSource) -> None: ...

    def get_source(self, job_id: str) -> StoredSource: ...


class ResultStore(Protocol):
    def put_result(self, job_id: str, document: dict[str, Any]) -> None: ...

    def get_result(self, job_id: str) -> dict[str, Any] | None: ...


class JobStore(JobRepository, JobQueue, SourceStore, ResultStore, Protocol):
    """Combined worker-facing boundary implemented by local and cloud adapters."""
