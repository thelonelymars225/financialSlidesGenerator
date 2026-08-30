from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from financial_slides_api.controllers.jobs import service_dependency, worker_dependency
from financial_slides_api.domain.jobs import (
    CreateJobCommand,
    JobConflictError,
    JobNotFoundError,
    JobStatus,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.main import app
from financial_slides_api.schemas.jobs import JobResponse, JobResultResponse
from financial_slides_api.services.jobs import ExtractionJobService
from financial_slides_api.worker import ExtractionJobWorker
from financial_slides_worker import (
    ExtractionService,
    ExtractionResult,
    ExtractionTelemetry,
    ExtractionTimeoutError,
)

REPOSITORY_ROOT = Path(__file__).parents[3]
INTEGRATION_FIXTURE = REPOSITORY_ROOT / "fixtures/integration/extraction-api-v0.1.json"
PDF_FIXTURE = REPOSITORY_ROOT / "services/worker/tests/fixtures/native-financial-report.pdf.b64"
EXTRACTED_DOCUMENT_SCHEMA = (
    REPOSITORY_ROOT / "packages/contracts/schemas/extracted-document-v0.1.schema.json"
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


class EmptyDocumentExtractor:
    media_type = "application/pdf"
    route = "native_pdf"

    def extract(self, source, context):
        return {
            "schemaVersion": "0.1",
            "documentId": "document-empty",
            "source": {"inputType": "file"},
            "pages": [
                {
                    "pageNumber": 1,
                    "width": 612,
                    "height": 792,
                    "coordinateUnit": "pt",
                    "blocks": [],
                }
            ],
            "warnings": [
                {
                    "code": "ocr.failed",
                    "severity": "error",
                    "message": "Local OCR failed for page 1.",
                }
            ],
        }


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


def empty_pdf_command() -> CreateJobCommand:
    return CreateJobCommand(
        owner_id="owner-1",
        input_mode="file",
        source_text=None,
        file_name="image-only.pdf",
        file_data=b"%PDF-1.7\nfixture",
        declared_media_type="application/pdf",
        deck_purpose="management-review",
        slide_count=8,
        request_key="empty-ocr-result",
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


def test_ocr_failure_cannot_mark_a_zero_block_job_succeeded(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    job = service.create(empty_pdf_command())
    extraction = ExtractionService(extractors=(EmptyDocumentExtractor(),))

    assert ExtractionJobWorker(store, extraction, clock=clock).run_available() == 1

    failed = service.get(job.id, "owner-1")
    assert failed.status is JobStatus.FAILED
    assert failed.failure.code == "ocr_failed"
    assert store.get_result(job.id) is None


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
                "slide_count": 4,
                "request_key": "api-success",
            },
        )
        assert submitted.status_code == 202
        job_id = submitted.json()["id"]
        assert submitted.json()["status"] == "queued"
        assert submitted.json()["slide_count"] == 4

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


def test_api_automatically_processes_job_in_background(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    worker = ExtractionJobWorker(store, SuccessfulExtraction(), clock=clock)
    app.dependency_overrides[service_dependency] = lambda: service
    app.dependency_overrides[worker_dependency] = lambda: worker
    client = TestClient(app)
    try:
        submitted = client.post(
            "/api/jobs",
            headers={"X-Owner-ID": "automatic-owner"},
            json={
                "input_mode": "text",
                "source_text": "Revenue increased by 14%.",
                "deck_purpose": "management-review",
                "slide_count": 8,
                "request_key": "automatic-processing",
            },
        )

        assert submitted.status_code == 202
        job_id = submitted.json()["id"]
        result = client.get(
            f"/api/jobs/{job_id}/result",
            headers={"X-Owner-ID": "automatic-owner"},
        )
        assert result.status_code == 200
        assert result.json()["job"]["status"] == "succeeded"
    finally:
        app.dependency_overrides.clear()


def test_real_api_queue_worker_result_vertical_slice_for_text_and_pdf(tmp_path) -> None:
    clock = MutableClock()
    service, store = service_and_store(tmp_path, clock)
    app.dependency_overrides[service_dependency] = lambda: service
    client = TestClient(app)
    pdf_base64 = "".join(PDF_FIXTURE.read_text(encoding="ascii").split())
    cases = (
        (
            {
                "input_mode": "text",
                "source_text": "Revenue increased to $12.4 million.",
                "deck_purpose": "management-review",
                "slide_count": 8,
                "request_key": "real-text",
            },
            "pasted_text",
        ),
        (
            {
                "input_mode": "file",
                "file_name": "quarterly-report.pdf",
                "file_content_base64": pdf_base64,
                "declared_media_type": "application/pdf",
                "deck_purpose": "management-review",
                "slide_count": 8,
                "request_key": "real-pdf",
            },
            "native_pdf",
        ),
    )
    try:
        for payload, route in cases:
            submitted = client.post(
                "/api/jobs",
                headers={"X-Owner-ID": "integration-owner"},
                json=payload,
            )
            assert submitted.status_code == 202
            job_id = submitted.json()["id"]
            assert (
                client.get(
                    f"/api/jobs/{job_id}/result",
                    headers={"X-Owner-ID": "integration-owner"},
                ).status_code
                == 409
            )
            assert (
                client.get(
                    f"/api/jobs/{job_id}",
                    headers={"X-Owner-ID": "another-owner"},
                ).status_code
                == 404
            )

            assert ExtractionJobWorker(store, clock=clock).run_available() == 1
            status = client.get(
                f"/api/jobs/{job_id}",
                headers={"X-Owner-ID": "integration-owner"},
            )
            result = client.get(
                f"/api/jobs/{job_id}/result",
                headers={"X-Owner-ID": "integration-owner"},
            )

            assert status.json()["status"] == "succeeded"
            assert status.json()["telemetry"]["route"] == route
            assert result.status_code == 200
            Draft202012Validator(
                json.loads(EXTRACTED_DOCUMENT_SCHEMA.read_text(encoding="utf-8"))
            ).validate(result.json()["document"])

            if route == "native_pdf":
                page = result.json()["document"]["pages"][0]
                table = next(block for block in page["blocks"] if block["type"] == "table")
                assert table["cells"][-1]["text"] == "$12.4m"
                assert table["source"]["boundingBox"]["unit"] == "pt"
    finally:
        app.dependency_overrides.clear()


def test_shared_frontend_fixture_matches_backend_response_models_and_contract() -> None:
    fixture = json.loads(INTEGRATION_FIXTURE.read_text(encoding="utf-8"))

    JobResultResponse.model_validate(fixture["successful_result"])
    JobResponse.model_validate(fixture["failed_job"])
    Draft202012Validator(
        json.loads(EXTRACTED_DOCUMENT_SCHEMA.read_text(encoding="utf-8"))
    ).validate(fixture["successful_result"]["document"])
    encoded_pdf = "".join(PDF_FIXTURE.read_text(encoding="ascii").split())
    assert b64decode(encoded_pdf, validate=True).startswith(b"%PDF")
