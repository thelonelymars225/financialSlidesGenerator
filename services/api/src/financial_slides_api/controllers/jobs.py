"""Thin HTTP transport for durable extraction jobs."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from financial_slides_api.domain.jobs import (
    JobConflictError,
    JobNotFoundError,
    JobNotReadyError,
)
from financial_slides_api.schemas.jobs import (
    CancelJobResponse,
    CreateJobRequest,
    JobResponse,
    JobResultResponse,
)
from financial_slides_api.services.jobs import ExtractionJobService, get_job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

OwnerId = Annotated[str, Header(alias="X-Owner-ID", min_length=1, max_length=128)]


def service_dependency() -> ExtractionJobService:
    return get_job_service()


JobService = Annotated[ExtractionJobService, Depends(service_dependency)]


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: CreateJobRequest,
    service: JobService,
    owner_id: OwnerId = "local-development",
) -> JobResponse:
    try:
        job = service.create(request.to_command(owner_id))
    except JobConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return JobResponse.from_job(job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    service: JobService,
    owner_id: OwnerId = "local-development",
) -> JobResponse:
    try:
        return JobResponse.from_job(service.get(str(job_id), owner_id))
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(
    job_id: UUID,
    service: JobService,
    owner_id: OwnerId = "local-development",
) -> JobResultResponse:
    try:
        job, document = service.result(str(job_id), owner_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except JobNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return JobResultResponse(job=JobResponse.from_job(job), document=document)


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
def cancel_job(
    job_id: UUID,
    service: JobService,
    owner_id: OwnerId = "local-development",
) -> CancelJobResponse:
    try:
        job = service.cancel(str(job_id), owner_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return CancelJobResponse(job=JobResponse.from_job(job))


@router.delete("/{job_id}/data", status_code=status.HTTP_204_NO_CONTENT)
def delete_job_data(
    job_id: UUID,
    service: JobService,
    owner_id: OwnerId = "local-development",
) -> Response:
    try:
        service.delete_data(str(job_id), owner_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
