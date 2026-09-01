"""Thin HTTP transport for durable extraction jobs."""

import os

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

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
from financial_slides_api.quotas import SubmissionIdentity
from financial_slides_api.services.jobs import ExtractionJobService, get_job_service, get_job_store
from financial_slides_api.security import Identity, RequestIdentity, require_manager
from financial_slides_api.worker import ExtractionJobWorker

router = APIRouter(prefix="/jobs", tags=["jobs"])

ManagerIdentity = Annotated[RequestIdentity, Depends(require_manager)]


def service_dependency() -> ExtractionJobService:
    return get_job_service()


JobService = Annotated[ExtractionJobService, Depends(service_dependency)]


def worker_dependency() -> ExtractionJobWorker:
    return ExtractionJobWorker(get_job_store())


JobWorker = Annotated[ExtractionJobWorker, Depends(worker_dependency)]


@router.post("", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    request: CreateJobRequest,
    background: BackgroundTasks,
    service: JobService,
    worker: JobWorker,
    identity: SubmissionIdentity,
) -> JobResponse:
    try:
        job = service.create(
            request.to_command(
                identity.organization_id,
                created_by=identity.user_id,
            )
        )
    except JobConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if os.getenv("WORKFLOW_BACKEND", "local").strip().lower() != "temporal":
        background.add_task(worker.run_available, 1)
    return JobResponse.from_job(job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    service: JobService,
    identity: Identity,
) -> JobResponse:
    try:
        return JobResponse.from_job(service.get(str(job_id), identity.organization_id))
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(
    job_id: UUID,
    service: JobService,
    identity: Identity,
) -> JobResultResponse:
    try:
        job, document = service.result(str(job_id), identity.organization_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except JobNotReadyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return JobResultResponse(job=JobResponse.from_job(job), document=document)


@router.post("/{job_id}/cancel", response_model=CancelJobResponse)
def cancel_job(
    job_id: UUID,
    service: JobService,
    identity: Identity,
) -> CancelJobResponse:
    try:
        job = service.cancel(str(job_id), identity.organization_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return CancelJobResponse(job=JobResponse.from_job(job))


@router.delete("/{job_id}/data", status_code=status.HTTP_204_NO_CONTENT)
def delete_job_data(
    job_id: UUID,
    service: JobService,
    identity: ManagerIdentity,
) -> Response:
    try:
        service.delete_data(str(job_id), identity.organization_id)
    except JobNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
