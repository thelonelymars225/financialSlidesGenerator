"""Boundaries for retention cleanup and metadata-only audit events."""

from datetime import datetime
from typing import Protocol


class RetentionStore(Protocol):
    def delete_job_data(self, job_id: str) -> int: ...

    def purge_job_data_before(self, cutoff: datetime, now: datetime) -> int: ...


class AuditSink(Protocol):
    def record(
        self,
        action: str,
        resource_id: str,
        owner_id: str | None,
        *,
        deleted_count: int = 0,
    ) -> None: ...
