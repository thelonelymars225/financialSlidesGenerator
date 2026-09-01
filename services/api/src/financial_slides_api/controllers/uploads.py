"""Authenticated direct-upload endpoints."""

import os
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from financial_slides_api.controllers.jobs import JobService, JobWorker
from financial_slides_api.domain.jobs import CreateJobCommand, JobConflictError
from financial_slides_api.infrastructure.supabase_uploads import (
    SupabaseUploadService,
    UploadIntegrityError,
    UploadNotFoundError,
)
from financial_slides_api.quotas import SubmissionIdentity
from financial_slides_api.schemas.jobs import JobResponse
from financial_slides_api.schemas.uploads import (
    CreateJobFromUploadRequest,
    CreateSignedUploadRequest,
    SignedUploadResponse,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])


@lru_cache(maxsize=1)
def get_upload_service() -> SupabaseUploadService:
    required = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SECRET_KEY")
    missing = [name for name in required if not os.getenv(name, "").strip()]
    if missing:
        raise RuntimeError("direct uploads require: " + ", ".join(missing))
    return SupabaseUploadService(
        os.environ["DATABASE_URL"],
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SECRET_KEY"],
        bucket=os.getenv("SUPABASE_SOURCE_BUCKET", "source-documents"),
    )


UploadService = Annotated[SupabaseUploadService, Depends(get_upload_service)]


@router.post("", response_model=SignedUploadResponse, status_code=status.HTTP_201_CREATED)
def create_signed_upload(
    request: CreateSignedUploadRequest,
    identity: SubmissionIdentity,
    uploads: UploadService,
) -> SignedUploadResponse:
    upload = uploads.create(
        identity.organization_id,
        identity.user_id,
        file_name=request.file_name,
        media_type=request.media_type,
        size_bytes=request.size_bytes,
        digest=request.sha256,
    )
    return SignedUploadResponse(**upload.__dict__)


@router.post("/{upload_id}/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job_from_upload(
    upload_id: UUID,
    request: CreateJobFromUploadRequest,
    background: BackgroundTasks,
    identity: SubmissionIdentity,
    uploads: UploadService,
    service: JobService,
    worker: JobWorker,
) -> JobResponse:
    try:
        source = uploads.verify(str(upload_id), identity.organization_id)
        job = service.create(
            CreateJobCommand(
                owner_id=identity.organization_id,
                organization_id=identity.organization_id,
                created_by=identity.user_id,
                input_mode="file",
                source_text=None,
                file_name=source.file_name,
                file_data=source.content,
                declared_media_type=source.media_type,
                deck_purpose=request.deck_purpose,
                slide_count=request.slide_count,
                request_key=request.request_key,
            )
        )
    except UploadNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UploadIntegrityError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except JobConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if os.getenv("WORKFLOW_BACKEND", "local").strip().lower() != "temporal":
        background.add_task(worker.run_available, 1)
    return JobResponse.from_job(job)
