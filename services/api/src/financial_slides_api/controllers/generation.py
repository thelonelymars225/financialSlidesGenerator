"""Thin HTTP transport for slide generation, preview, retry, and download."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

from financial_slides_api.domain.generation import (
    GenerationConflictError,
    GenerationNotFoundError,
    GenerationNotReadyError,
)
from financial_slides_api.domain.jobs import JobNotFoundError, JobNotReadyError
from financial_slides_api.schemas.generation import (
    GenerationJobResponse,
    GenerationResultResponse,
    StartGenerationRequest,
)
from financial_slides_api.quotas import SubmissionIdentity
from financial_slides_api.services.generation import (
    SlideGenerationService,
    get_generation_service,
)
from financial_slides_api.security import Identity, RequestIdentity, require_manager

router = APIRouter(tags=["slide-generation"])
ManagerIdentity = Annotated[RequestIdentity, Depends(require_manager)]


def generation_service_dependency() -> SlideGenerationService:
    return get_generation_service()


GenerationService = Annotated[SlideGenerationService, Depends(generation_service_dependency)]


def _not_found(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _conflict(error: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


@router.post(
    "/jobs/{extraction_job_id}/slides",
    response_model=GenerationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_generation(
    extraction_job_id: UUID,
    request: StartGenerationRequest,
    background: BackgroundTasks,
    service: GenerationService,
    identity: SubmissionIdentity,
) -> GenerationJobResponse:
    try:
        job = service.start(
            str(extraction_job_id),
            identity.organization_id,
            request.deck_type,
            request_key=(request.request_key or f"auto:{extraction_job_id}:{request.deck_type}"),
            density_profile=request.density,
        )
    except JobNotFoundError as error:
        raise _not_found(error) from error
    except (JobNotReadyError, GenerationConflictError) as error:
        raise _conflict(error) from error
    background.add_task(service.run, job.id)
    return GenerationJobResponse.from_job(job)


@router.get("/slide-jobs/{job_id}", response_model=GenerationJobResponse)
def get_generation(
    job_id: UUID,
    service: GenerationService,
    identity: Identity,
) -> GenerationJobResponse:
    try:
        return GenerationJobResponse.from_job(
            service.get(str(job_id), identity.organization_id)
        )
    except GenerationNotFoundError as error:
        raise _not_found(error) from error


@router.get("/slide-jobs/{job_id}/result", response_model=GenerationResultResponse)
def get_generation_result(
    job_id: UUID,
    service: GenerationService,
    identity: Identity,
) -> GenerationResultResponse:
    try:
        job = service.result(str(job_id), identity.organization_id)
    except GenerationNotFoundError as error:
        raise _not_found(error) from error
    except GenerationNotReadyError as error:
        raise _conflict(error) from error
    return GenerationResultResponse(
        job=GenerationJobResponse.from_job(job),
        slide_spec=job.slide_spec or {},
        download_url=f"/api/slide-jobs/{job.id}/artifact",
    )


@router.get("/slide-jobs/{job_id}/artifact")
def download_artifact(
    job_id: UUID,
    service: GenerationService,
    identity: Identity,
) -> Response:
    try:
        artifact = service.artifact(str(job_id), identity.organization_id)
    except GenerationNotFoundError as error:
        raise _not_found(error) from error
    except GenerationNotReadyError as error:
        raise _conflict(error) from error
    return Response(
        artifact,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="financial-slides-{job_id}.pptx"'},
    )


@router.post("/slide-jobs/{job_id}/retry", response_model=GenerationJobResponse)
def retry_generation(
    job_id: UUID,
    background: BackgroundTasks,
    service: GenerationService,
    identity: Identity,
) -> GenerationJobResponse:
    try:
        job = service.retry(str(job_id), identity.organization_id)
    except GenerationNotFoundError as error:
        raise _not_found(error) from error
    except GenerationConflictError as error:
        raise _conflict(error) from error
    background.add_task(service.run, job.id)
    return GenerationJobResponse.from_job(job)


@router.delete("/slide-jobs/{job_id}/output", status_code=status.HTTP_204_NO_CONTENT)
def delete_generation_output(
    job_id: UUID,
    service: GenerationService,
    identity: ManagerIdentity,
) -> Response:
    try:
        service.delete_output(str(job_id), identity.organization_id)
    except GenerationNotFoundError as error:
        raise _not_found(error) from error
    except GenerationConflictError as error:
        raise _conflict(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
