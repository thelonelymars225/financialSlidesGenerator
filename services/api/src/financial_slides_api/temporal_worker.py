"""Temporal workflow/activity worker plus transactional-outbox pump."""

import asyncio
import contextlib
import os

from temporalio.worker import Worker

from financial_slides_api.workflow_activities import run_extraction_activity
from financial_slides_api.workflow_outbox import (
    PostgresWorkflowOutbox,
    dispatch_outbox_once,
    temporal_client_from_environment,
)
from financial_slides_api.workflows import ExtractionWorkflow


async def _pump_outbox(outbox: PostgresWorkflowOutbox, client) -> None:
    while True:
        processed = await dispatch_outbox_once(outbox, client)
        await asyncio.sleep(0 if processed else 1)


async def run() -> None:
    database_url = os.environ["DATABASE_URL"]
    client = await temporal_client_from_environment()
    outbox_task = asyncio.create_task(
        _pump_outbox(PostgresWorkflowOutbox(database_url), client)
    )
    worker = Worker(
        client,
        task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "financial-slides-extraction-v1"),
        workflows=[ExtractionWorkflow],
        activities=[run_extraction_activity],
    )
    try:
        await worker.run()
    finally:
        outbox_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await outbox_task


if __name__ == "__main__":
    asyncio.run(run())
