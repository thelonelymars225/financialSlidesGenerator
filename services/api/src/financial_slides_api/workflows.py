"""Deterministic Temporal workflows; payloads contain identifiers, never report data."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from financial_slides_api.workflow_models import ExtractionWorkflowInput

with workflow.unsafe.imports_passed_through():
    from financial_slides_api.workflow_activities import run_extraction_activity

@workflow.defn(name="financial-slides.extraction.v1")
class ExtractionWorkflow:
    @workflow.run
    async def run(self, request: ExtractionWorkflowInput) -> bool:
        return await workflow.execute_activity(
            run_extraction_activity,
            request,
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2,
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=3,
            ),
        )
