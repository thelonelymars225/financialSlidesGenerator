"""HTTP schemas for bounded slide-generation jobs."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from financial_slides_api.domain.generation import GenerationJob


class StartGenerationRequest(BaseModel):
    deck_type: Literal["management-review", "board-update", "investor-summary"]
    density: Literal["concise", "balanced", "detailed"] = "balanced"
    request_key: str | None = Field(default=None, min_length=1, max_length=128)


class GenerationFailureResponse(BaseModel):
    code: str
    message: str
    retryable: bool


class AnalysisTelemetryResponse(BaseModel):
    mode: Literal["hosted", "deterministic"]
    provider: str
    model: str
    fallback_used: bool
    provider_calls: int
    external_cost_usd: float


class GenerationJobResponse(BaseModel):
    id: UUID
    extraction_job_id: UUID
    deck_type: str
    slide_count: int
    density: Literal["concise", "balanced", "detailed"]
    status: Literal["queued", "analyzing", "rendering", "succeeded", "failed"]
    progress: int
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    failure: GenerationFailureResponse | None
    analysis: AnalysisTelemetryResponse | None

    @classmethod
    def from_job(cls, job: GenerationJob) -> "GenerationJobResponse":
        return cls(
            id=UUID(job.id),
            extraction_job_id=UUID(job.extraction_job_id),
            deck_type=job.deck_type,
            slide_count=job.slide_count,
            density=job.density_profile.value,
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
            analysis=(
                AnalysisTelemetryResponse(
                    mode=(
                        "deterministic"
                        if job.analysis_telemetry.provider == "deterministic"
                        else "hosted"
                    ),
                    provider=job.analysis_telemetry.provider,
                    model=job.analysis_telemetry.model,
                    fallback_used=job.analysis_telemetry.fallback_used,
                    provider_calls=job.analysis_telemetry.provider_calls,
                    external_cost_usd=job.analysis_telemetry.external_cost_usd,
                )
                if job.analysis_telemetry
                else None
            ),
        )


class GenerationResultResponse(BaseModel):
    job: GenerationJobResponse
    slide_spec: dict[str, Any]
    download_url: str
