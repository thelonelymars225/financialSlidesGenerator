"""Validated direct-upload API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CreateSignedUploadRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=180)
    media_type: Literal["application/pdf"] = "application/pdf"
    size_bytes: int = Field(ge=1, le=25 * 1024 * 1024)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("file_name must be a plain file name")
        if not value.lower().endswith(".pdf"):
            raise ValueError("only PDF files are supported")
        return value


class SignedUploadResponse(BaseModel):
    id: UUID
    object_key: str
    signed_url: str
    expires_at: datetime


class CreateJobFromUploadRequest(BaseModel):
    deck_purpose: Literal["management-review", "board-update", "investor-summary"]
    slide_count: int = Field(ge=4, le=20)
    request_key: str = Field(min_length=1, max_length=128)
