import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from financial_slides_api.controllers.generation import generation_service_dependency
from financial_slides_api.controllers.jobs import service_dependency
from financial_slides_api.controllers.privacy import retention_policy_dependency
from financial_slides_api.domain.generation import GenerationNotReadyError, GenerationStatus
from financial_slides_api.domain.jobs import CreateJobCommand, JobStatus
from financial_slides_api.infrastructure.audit import MetadataAuditLogger
from financial_slides_api.infrastructure.deterministic_analysis import (
    DeterministicAnalysisProvider,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.main import app
from financial_slides_api.services.analysis import FinancialAnalysisService
from financial_slides_api.services.generation import SlideGenerationService
from financial_slides_api.services.jobs import ExtractionJobService
from financial_slides_api.services.privacy import (
    RetentionPolicy,
    retention_policy_from_environment,
)
from financial_slides_api.worker import ExtractionJobWorker


@dataclass
class MutableClock:
    value: datetime = datetime(2026, 7, 29, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance_hours(self, hours: int) -> None:
        self.value += timedelta(hours=hours)


class RecordingRenderer:
    def render(self, slide_spec: dict) -> bytes:
        del slide_spec
        return b"PK\x03\x04private-presentation"


def command(owner_id: str, text: str, request_key: str) -> CreateJobCommand:
    return CreateJobCommand(
        owner_id=owner_id,
        input_mode="text",
        source_text=text,
        file_name=None,
        file_data=None,
        declared_media_type=None,
        deck_purpose="management-review",
        slide_count=8,
        request_key=request_key,
    )


def extraction_fixture(tmp_path, clock: MutableClock):
    store = SQLiteJobStore(tmp_path / "privacy.sqlite3")
    service = ExtractionJobService(
        store,
        store,
        store,
        clock=clock,
        retention=store,
        policy=RetentionPolicy(),
        audit=MetadataAuditLogger(),
    )
    return service, store


def test_retention_defaults_are_explicit_configurable_and_bounded() -> None:
    defaults = retention_policy_from_environment({})
    configured = retention_policy_from_environment(
        {
            "FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS": "12",
            "FINANCIAL_SLIDES_ARTIFACT_RETENTION_HOURS": "48",
        }
    )

    assert defaults == RetentionPolicy(source_hours=24, artifact_hours=24)
    assert configured == RetentionPolicy(source_hours=12, artifact_hours=48)
    with pytest.raises(RuntimeError, match="between 1 and"):
        retention_policy_from_environment({"FINANCIAL_SLIDES_SOURCE_RETENTION_HOURS": "0"})


def test_owner_can_delete_source_and_result_without_content_in_audit_log(
    tmp_path,
    caplog,
) -> None:
    clock = MutableClock()
    service, store = extraction_fixture(tmp_path, clock)
    secret_source = "CONFIDENTIAL revenue and api-key-test-secret"
    job = service.create(command("owner-1", secret_source, "privacy-delete"))
    assert ExtractionJobWorker(store, clock=clock).run_available() == 1
    assert service.result(job.id, "owner-1")[1]
    app.dependency_overrides[service_dependency] = lambda: service
    client = TestClient(app)
    try:
        with caplog.at_level(logging.INFO, logger="financial_slides.audit"):
            wrong_owner = client.delete(
                f"/api/jobs/{job.id}/data",
                headers={"X-Owner-ID": "owner-2"},
            )
            deleted = client.delete(
                f"/api/jobs/{job.id}/data",
                headers={"X-Owner-ID": "owner-1"},
            )
            repeated = client.delete(
                f"/api/jobs/{job.id}/data",
                headers={"X-Owner-ID": "owner-1"},
            )

        assert wrong_owner.status_code == 404
        assert deleted.status_code == 204
        assert repeated.status_code == 204
        assert service.get(job.id, "owner-1").status is JobStatus.SUCCEEDED
        with pytest.raises(KeyError):
            store.get_source(job.id)
        assert store.get_result(job.id) is None
        audit = " ".join(caplog.messages)
        assert "source_data_deleted" in audit
        assert secret_source not in audit
        assert "api-key-test-secret" not in audit
        assert "owner-1" not in audit
    finally:
        app.dependency_overrides.clear()


def test_expired_source_is_removed_and_unfinished_job_is_cancelled(tmp_path) -> None:
    clock = MutableClock()
    service, store = extraction_fixture(tmp_path, clock)
    job = service.create(command("owner-1", "Short-lived source", "privacy-expiry"))

    clock.advance_hours(25)
    retained_metadata = service.get(job.id, "owner-1")

    assert retained_metadata.status is JobStatus.CANCELLED
    with pytest.raises(KeyError):
        store.get_source(job.id)


def test_owner_can_delete_generated_output_and_expiry_preserves_job_metadata(
    tmp_path,
) -> None:
    clock = MutableClock()
    extraction, store = extraction_fixture(tmp_path, clock)
    source_job = extraction.create(
        command(
            "owner-1",
            "Revenue reached $12.4 million in Q2 2026.",
            "privacy-generation",
        )
    )
    assert ExtractionJobWorker(store, clock=clock).run_available() == 1
    generation = SlideGenerationService(
        extraction,
        FinancialAnalysisService(DeterministicAnalysisProvider()),
        RecordingRenderer(),
        clock=clock,
        policy=RetentionPolicy(),
        audit=MetadataAuditLogger(),
    )
    first = generation.start(source_job.id, "owner-1", "management-review")
    asyncio.run(generation.run(first.id))
    assert generation.get(first.id, "owner-1").status is GenerationStatus.SUCCEEDED

    app.dependency_overrides[generation_service_dependency] = lambda: generation
    client = TestClient(app)
    try:
        assert (
            client.delete(
                f"/api/slide-jobs/{first.id}/output",
                headers={"X-Owner-ID": "owner-2"},
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/slide-jobs/{first.id}/output",
                headers={"X-Owner-ID": "owner-1"},
            ).status_code
            == 204
        )
        with pytest.raises(GenerationNotReadyError):
            generation.result(first.id, "owner-1")

        second = generation.start(source_job.id, "owner-1", "management-review")
        asyncio.run(generation.run(second.id))
        clock.advance_hours(25)
        expired = generation.get(second.id, "owner-1")
        assert expired.status is GenerationStatus.SUCCEEDED
        with pytest.raises(GenerationNotReadyError):
            generation.result(second.id, "owner-1")
    finally:
        app.dependency_overrides.clear()


def test_retention_policy_endpoint_reports_active_defaults() -> None:
    app.dependency_overrides[retention_policy_dependency] = lambda: RetentionPolicy(
        source_hours=12,
        artifact_hours=36,
    )
    client = TestClient(app)
    try:
        response = client.get("/api/privacy/retention")
        assert response.status_code == 200
        assert response.json() == {
            "source_retention_hours": 12,
            "artifact_retention_hours": 36,
        }
    finally:
        app.dependency_overrides.clear()
