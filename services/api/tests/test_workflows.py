import asyncio
from uuid import uuid4

from financial_slides_api.workflow_models import ExtractionWorkflowInput
from financial_slides_api.workflow_outbox import OutboxEvent, dispatch_event


class RecordingTemporalClient:
    def __init__(self) -> None:
        self.calls = []

    async def start_workflow(self, workflow, request, **options):
        self.calls.append((workflow, request, options))


def test_temporal_dispatch_uses_opaque_ids_and_deterministic_workflow_id() -> None:
    organization_id = str(uuid4())
    job_id = str(uuid4())
    event = OutboxEvent(
        id=str(uuid4()),
        event_type="extraction.requested",
        aggregate_id=job_id,
        organization_id=organization_id,
        payload={"job_id": job_id, "organization_id": organization_id},
    )
    client = RecordingTemporalClient()

    asyncio.run(dispatch_event(client, event))

    _, request, options = client.calls[0]
    assert request == ExtractionWorkflowInput(job_id, organization_id)
    assert options["id"] == f"extract:{organization_id}:{job_id}"
    assert "source" not in repr(request).lower()


def test_temporal_dispatch_rejects_unknown_outbox_events() -> None:
    event = OutboxEvent("event", "unknown", "job", "organization", {})
    try:
        asyncio.run(dispatch_event(RecordingTemporalClient(), event))
    except ValueError as error:
        assert str(error) == "unsupported_event_type"
    else:
        raise AssertionError("unsupported outbox event was accepted")
