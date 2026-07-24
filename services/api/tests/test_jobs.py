from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from financial_slides_api.controllers.jobs import service_dependency
from financial_slides_api.domain.jobs import (
    CreateJobCommand,
    JobConflictError,
    JobNotFoundError,
    JobStatus,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.main import app
from financial_slides_api.services.jobs import ExtractionJobService
from financial_slides_api.worker import ExtractionJobWorker
from financial_slides_worker import (
    ExtractionResult,
    ExtractionTelemetry,
    ExtractionTimeoutError,
)


@dataclass
class MutableClock:
    value: datetime = datetime(2026, 7, 24, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class SuccessfulExtraction:
    def extract_text(self, source) -> ExtractionResult:
        return ExtractionResult(
            document={
                "schemaVersion": "0.1",
                "documentId": "document-test",
                "source": {"inputType": "text"},
                "pages": [],
                "warnings": [],
            },
            telemetry=ExtractionTelemetry(
                route="pasted_text",
                duration_ms=12.5,
                external_cost_usd=0,
            ),
        )

    def extract_file(self, source) -> ExtractionResult:
        return self.extract_text(source)


class TimedOutExtraction(SuccessfulExtraction):
    def extract_text(self, source) -> ExtractionResult:
        raise ExtractionTimeoutError()


def command(
    text: str,
    *,
    request_key: str | None = None,
    owner_id: str = "owner-1",
) -> CreateJobCommand:
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


def service_and_store(tmp_path, clock: MutableClock, *, max_attempts: int = 3):
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    service = ExtractionJobService(
        store,
        store,
        store,
        clock=clock,
        max_attempts=max_attempts,
    )
    return service, store


def test_job_survives_restart_and_worker_emits_canonical_result(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)

    created = service.create(command("Revenue reached $12.4 million."))
    duplicate = service.create(command("Revenue reached $12.4 million."))

    assert duplicate.id == created.id
    assert created.status is JobStatus.QUEUED

    reopened_store = SQLiteJobStore(store.database_path)
    worker = ExtractionJobWorker(
        reopened_store,
        clock=clock,
    )
    assert worker.run_available() == 1

    restarted_service = ExtractionJobService(
        reopened_store,
        reopened_store,
        reopened_store,
        clock=clock,
    )
    finished, document = restarted_service.result(created.id, "owner-1")

    assert finished.status is JobStatus.SUCCEEDED
    assert finished.attempt_count == 1
    assert finished.telemetry.route == "pasted_text"
    assert finished.telemetry.external_cost_usd == 0
    assert document["schemaVersion"] == "0.1"
    assert document["source"]["inputType"] == "text"
    assert document["pages"][0]["blocks"][0]["text"].startswith("Revenue")


def test_request_key_conflict_and_owner_authorization(tmp_path) -> None:
    clock = MutableClock()
    service, _ = service_and_store(tmp_path, clock)
    job = service.create(command("First source", request_key="same-key"))

    with pytest.raises(JobConflictError):
        service.create(command("Different source", request_key="same-key"))

    with pytest.raises(JobNotFoundError):
        service.get(job.id, "another-owner")


def test_cancelled_job_is_not_claimed(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    job = service.create(command("Cancel this job"))

    cancelled = service.cancel(job.id, "owner-1")

    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.finished_at == clock.value
    assert ExtractionJobWorker(store, SuccessfulExtraction(), clock=clock).run_available() == 0


def test_retry_backoff_and_attempt_limit_are_bounded(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock, max_attempts=2)
    job = service.create(command("Retry this source"))
    worker = ExtractionJobWorker(store, TimedOutExtraction(), clock=clock)

    assert worker.run_available() == 1
    first_failure = service.get(job.id, "owner-1")
    assert first_failure.status is JobStatus.QUEUED
    assert first_failure.attempt_count == 1
    assert first_failure.failure.code == "extraction_timeout"
    assert worker.run_available() == 0

    clock.advance(1)
    assert worker.run_available() == 1
    terminal = service.get(job.id, "owner-1")
    assert terminal.status is JobStatus.FAILED
    assert terminal.attempt_count == 2
    assert terminal.failure.code == "extraction_timeout"


def test_interrupted_worker_lease_is_recovered_after_restart(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    job = service.create(command("Recover this source"))

    claimed = store.claim_next(clock())
    assert claimed.status is JobStatus.RUNNING
    assert claimed.attempt_count == 1

    clock.advance(301)
    reopened_store = SQLiteJobStore(store.database_path)
    restarted_worker = ExtractionJobWorker(
        reopened_store,
        SuccessfulExtraction(),
        clock=clock,
        lease_seconds=300,
    )

    assert restarted_worker.run_available() == 1
    recovered = service.get(job.id, "owner-1")
    assert recovered.status is JobStatus.SUCCEEDED
    assert recovered.attempt_count == 2
    assert recovered.telemetry.retries == 1


def test_worker_enforces_per_run_concurrency_limit(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    jobs = [service.create(command(f"Source {index}")) for index in range(3)]
    worker = ExtractionJobWorker(
        store,
        SuccessfulExtraction(),
        clock=clock,
        max_jobs_per_run=2,
    )

    assert worker.run_available(requested_limit=99) == 2
    statuses = [service.get(job.id, "owner-1").status for job in jobs]
    assert statuses.count(JobStatus.SUCCEEDED) == 2
    assert statuses.count(JobStatus.QUEUED) == 1


def test_api_submit_poll_result_and_typed_failure(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    app.dependency_overrides[service_dependency] = lambda: service
    client = TestClient(app)
    try:
        submitted = client.post(
            "/api/jobs",
            headers={"X-Owner-ID": "api-owner"},
            json={
                "input_mode": "text",
                "source_text": "Revenue increased by 14%.",
                "deck_purpose": "management-review",
                "slide_count": 8,
                "request_key": "api-success",
            },
        )
        assert submitted.status_code == 202
        job_id = submitted.json()["id"]
        assert submitted.json()["status"] == "queued"

        worker = ExtractionJobWorker(store, SuccessfulExtraction(), clock=clock)
        assert worker.run_available() == 1

        status_response = client.get(
            f"/api/jobs/{job_id}",
            headers={"X-Owner-ID": "api-owner"},
        )
        assert status_response.json()["status"] == "succeeded"
        result = client.get(
            f"/api/jobs/{job_id}/result",
            headers={"X-Owner-ID": "api-owner"},
        )
        assert result.status_code == 200
        assert result.json()["document"]["schemaVersion"] == "0.1"

        failed_submission = client.post(
            "/api/jobs",
            headers={"X-Owner-ID": "api-owner"},
            json={
                "input_mode": "file",
                "file_name": "unsupported.bin",
                "file_content_base64": b64encode(b"not a supported file").decode(),
                "deck_purpose": "management-review",
                "slide_count": 8,
                "request_key": "api-failure",
            },
        )
        failed_id = failed_submission.json()["id"]
        native_worker = ExtractionJobWorker(store, clock=clock)
        assert native_worker.run_available() == 1
        failed = client.get(
            f"/api/jobs/{failed_id}",
            headers={"X-Owner-ID": "api-owner"},
        )
        assert failed.json()["status"] == "failed"
        assert failed.json()["failure"]["code"] == "unsupported_file"
        assert (
            client.get(
                f"/api/jobs/{failed_id}/result",
                headers={"X-Owner-ID": "api-owner"},
            ).status_code
            == 409
        )
    finally:
        app.dependency_overrides.clear()
