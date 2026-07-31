"""HTTP schemas for bounded slide-generation jobs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from financial_slides_api.domain.generation import GenerationJob


class StartGenerationRequest(BaseModel):
    deck_type: Literal["management-review", "board-update", "investor-summary"]


class GenerationFailureResponse(BaseModel):
    code: str
    message: str
    retryable: bool


class GenerationJobResponse(BaseModel):
    id: UUID
    extraction_job_id: UUID
    deck_type: str
    slide_count: int
    status: Literal["queued", "analyzing", "rendering", "succeeded", "failed"]
    progress: int
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    failure: GenerationFailureResponse | None

    @classmethod
    def from_job(cls, job: GenerationJob) -> "GenerationJobResponse":
        return cls(
            id=UUID(job.id),
            extraction_job_id=UUID(job.extraction_job_id),
            deck_type=job.deck_type,
            slide_count=job.slide_count,
            status=job.status.value,
            progress=job.progress,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            created_at=job.created_at,
            updated_at=job.updated_at,
            failure=(
                GenerationFailureResponse(
                    code=job.failure.code,
                    message=job.failure.message,
                    retryable=job.failure.retryable,
                )
                if job.failure
                else None
            ),
        )


class GenerationResultResponse(BaseModel):
    job: GenerationJobResponse
    slide_spec: dict[str, Any]
    download_url: str
