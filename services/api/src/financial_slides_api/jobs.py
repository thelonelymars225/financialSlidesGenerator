from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

router = APIRouter(prefix="/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    input_mode: Literal["file", "text"]
    source_text: str | None = None
    file_name: str | None = None
    deck_purpose: Literal["management-review", "board-update", "investor-summary"]
    slide_count: int = Field(ge=5, le=20)

    @model_validator(mode="after")
    def source_matches_mode(self) -> "CreateJobRequest":
        if self.input_mode == "text" and not (self.source_text or "").strip():
            raise ValueError("source_text is required when input_mode is text")
        if self.input_mode == "file" and not (self.file_name or "").strip():
            raise ValueError("file_name is required when input_mode is file")
        return self


class JobResponse(CreateJobRequest):
    id: UUID
    status: Literal["queued"] = "queued"


@router.post("", response_model=JobResponse, status_code=202)
def create_job(request: CreateJobRequest) -> JobResponse:
    """Validate and queue a generation request.

    Persistence and a real worker queue are intentionally deferred until those
    infrastructure decisions have been benchmarked.
    """
    return JobResponse(id=uuid4(), **request.model_dump())
