"""Immutable slide-generation job state and safe typed failures."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any


class GenerationStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class GenerationFailure:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class GenerationJob:
    id: str
    extraction_job_id: str
    owner_id: str
    deck_type: str
    slide_count: int
    status: GenerationStatus
    progress: int
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    failure: GenerationFailure | None = None
    slide_spec: dict[str, Any] | None = None
    artifact: bytes | None = None


class GenerationError(Exception):
    """Base generation-domain error."""


class GenerationNotFoundError(GenerationError):
    """The job is missing or belongs to another owner."""


class GenerationNotReadyError(GenerationError):
    """The requested result is not available."""


class GenerationConflictError(GenerationError):
    """The requested transition is not allowed."""


def transition(
    job: GenerationJob,
    status: GenerationStatus,
    progress: int,
    now: datetime,
) -> GenerationJob:
    return replace(job, status=status, progress=progress, updated_at=now)
