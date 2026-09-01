"""Worker activities kept outside the deterministic workflow sandbox."""

import asyncio

from temporalio import activity
from temporalio.exceptions import ApplicationError

from financial_slides_api.services.jobs import get_job_store
from financial_slides_api.worker import ExtractionJobWorker
from financial_slides_api.workflow_models import ExtractionWorkflowInput


@activity.defn(name="financial-slides.extract-job.v1")
async def run_extraction_activity(request: ExtractionWorkflowInput) -> bool:
    activity.heartbeat("claiming")
    completed = await asyncio.to_thread(
        ExtractionJobWorker(get_job_store()).run_job,
        request.job_id,
        request.organization_id,
    )
    activity.heartbeat("finished")
    if not completed:
        raise ApplicationError(
            "extraction did not complete successfully",
            type="ExtractionIncomplete",
        )
    return True
