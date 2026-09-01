"""Transactional outbox dispatcher for at-least-once Temporal workflow starts."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from financial_slides_api.workflow_models import ExtractionWorkflowInput
from financial_slides_api.workflows import ExtractionWorkflow


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    event_type: str
    aggregate_id: str
    organization_id: str
    payload: dict[str, Any]


class PostgresWorkflowOutbox:
    def __init__(self, database_url: str, *, lease_seconds: int = 60) -> None:
        self._database_url = database_url
        self._lease_seconds = lease_seconds

    def claim_batch(self, limit: int = 10) -> list[OutboxEvent]:
        if not 1 <= limit <= 100:
            raise ValueError("outbox batch limit must be between 1 and 100")
        stale_before = datetime.now(UTC) - timedelta(seconds=self._lease_seconds)
        with psycopg.connect(self._database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                with claimed as (
                    select id
                    from financial_slides.workflow_outbox
                    where delivered_at is null
                        and (claimed_at is null or claimed_at < %s)
                    order by created_at
                    for update skip locked
                    limit %s
                )
                update financial_slides.workflow_outbox as event set
                    claimed_at=now(),
                    attempt_count=event.attempt_count + 1
                from claimed
                where event.id = claimed.id
                returning event.id, event.event_type, event.aggregate_id,
                    event.organization_id, event.payload
                """,
                (stale_before, limit),
            ).fetchall()
        return [
            OutboxEvent(
                id=str(row["id"]),
                event_type=str(row["event_type"]),
                aggregate_id=str(row["aggregate_id"]),
                organization_id=str(row["organization_id"]),
                payload=dict(row["payload"]),
            )
            for row in rows
        ]

    def mark_delivered(self, event_id: str) -> None:
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                update financial_slides.workflow_outbox
                set delivered_at=now(), last_error_code=null
                where id=%s and delivered_at is null
                """,
                (event_id,),
            )

    def mark_failed(self, event_id: str, error_code: str) -> None:
        safe_code = "".join(
            character for character in error_code.lower() if character.isalnum() or character == "_"
        )[:80] or "dispatch_failed"
        with psycopg.connect(self._database_url) as connection:
            connection.execute(
                """
                update financial_slides.workflow_outbox
                set claimed_at=null, last_error_code=%s
                where id=%s and delivered_at is null
                """,
                (safe_code, event_id),
            )


async def temporal_client_from_environment() -> Client:
    address = os.environ["TEMPORAL_ADDRESS"]
    namespace = os.environ["TEMPORAL_NAMESPACE"]
    api_key = os.getenv("TEMPORAL_API_KEY", "").strip() or None
    return await Client.connect(
        address,
        namespace=namespace,
        tls=bool(api_key),
        api_key=api_key,
    )


async def dispatch_event(client: Client, event: OutboxEvent) -> None:
    if event.event_type != "extraction.requested":
        raise ValueError("unsupported_event_type")
    request = ExtractionWorkflowInput(
        job_id=str(event.payload["job_id"]),
        organization_id=str(event.payload["organization_id"]),
    )
    workflow_id = f"extract:{request.organization_id}:{request.job_id}"
    try:
        await client.start_workflow(
            ExtractionWorkflow.run,
            request,
            id=workflow_id,
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "financial-slides-extraction-v1"),
        )
    except WorkflowAlreadyStartedError:
        return


async def dispatch_outbox_once(
    outbox: PostgresWorkflowOutbox,
    client: Client,
    *,
    limit: int = 10,
) -> int:
    events = await asyncio.to_thread(outbox.claim_batch, limit)
    for event in events:
        try:
            await dispatch_event(client, event)
        except Exception as error:
            await asyncio.to_thread(outbox.mark_failed, event.id, type(error).__name__)
        else:
            await asyncio.to_thread(outbox.mark_delivered, event.id)
    return len(events)
