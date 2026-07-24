"""Versioned API schemas for extraction job submission and status."""

from base64 import b64decode
from binascii import Error as Base64Error
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from financial_slides_api.domain.jobs import CreateJobCommand, Job

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024


class CreateJobRequest(BaseModel):
    input_mode: Literal["file", "text"]
    source_text: str | None = None
    file_name: str | None = None
    file_content_base64: str | None = None
    declared_media_type: str | None = None
    deck_purpose: Literal["management-review", "board-update", "investor-summary"]
    slide_count: int = Field(ge=5, le=20)
    request_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def source_matches_mode(self) -> "CreateJobRequest":
        if self.input_mode == "text":
            if not (self.source_text or "").strip():
                raise ValueError("source_text is required when input_mode is text")
            if len((self.source_text or "").encode("utf-8")) > MAX_TEXT_BYTES:
                raise ValueError(f"source_text exceeds the {MAX_TEXT_BYTES}-byte limit")
        if self.input_mode == "file":
            if not (self.file_name or "").strip():
                raise ValueError("file_name is required when input_mode is file")
            if not self.file_content_base64:
                raise ValueError("file_content_base64 is required when input_mode is file")
            try:
                file_data = b64decode(self.file_content_base64, validate=True)
            except (Base64Error, ValueError) as error:
                raise ValueError("file_content_base64 must be valid base64") from error
            if len(file_data) > MAX_FILE_BYTES:
                raise ValueError(f"file content exceeds the {MAX_FILE_BYTES}-byte limit")
        return self

    def to_command(self, owner_id: str) -> CreateJobCommand:
        file_data: bytes | None = None
        if self.file_content_base64 is not None:
            try:
                file_data = b64decode(self.file_content_base64, validate=True)
            except (Base64Error, ValueError) as error:
                raise ValueError("file_content_base64 must be valid base64") from error
        return CreateJobCommand(
            owner_id=owner_id,
            input_mode=self.input_mode,
            source_text=self.source_text,
            file_name=self.file_name,
            file_data=file_data,
            declared_media_type=self.declared_media_type,
            deck_purpose=self.deck_purpose,
            slide_count=self.slide_count,
            request_key=self.request_key,
        )


class FailureResponse(BaseModel):
    code: str
    message: str


class TelemetryResponse(BaseModel):
    route: str
    duration_ms: float
    retries: int
    external_cost_usd: float


class JobResponse(BaseModel):
    id: UUID
    input_mode: Literal["file", "text"]
    file_name: str | None
    deck_purpose: str
    slide_count: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    max_attempts: int
    failure: FailureResponse | None
    telemetry: TelemetryResponse | None

    @classmethod
    def from_job(cls, job: Job) -> "JobResponse":
        return cls(
            id=UUID(job.id),
            input_mode=job.input_mode,
            file_name=job.file_name,
            deck_purpose=job.deck_purpose,
            slide_count=job.slide_count,
            status=job.status.value,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            failure=(
                FailureResponse(code=job.failure.code, message=job.failure.message)
                if job.failure
                else None
            ),
            telemetry=(
                TelemetryResponse(
                    route=job.telemetry.route,
                    duration_ms=job.telemetry.duration_ms,
                    retries=job.telemetry.retries,
                    external_cost_usd=job.telemetry.external_cost_usd,
                )
                if job.telemetry
                else None
            ),
        )


class JobResultResponse(BaseModel):
    job: JobResponse
    document: dict[str, Any]


class CancelJobResponse(BaseModel):
    job: JobResponse
