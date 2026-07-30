from datetime import UTC, datetime

from financial_slides_api.domain.jobs import CreateJobCommand, JobStatus
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.services.jobs import ExtractionJobService
from financial_slides_api.worker import ExtractionJobWorker, run_watch_loop
from financial_slides_worker import ExtractionResult, ExtractionTelemetry


class SuccessfulExtraction:
    def extract_text(self, source) -> ExtractionResult:
        return ExtractionResult(
            document={
                "schemaVersion": "0.1",
                "documentId": "watch-test",
                "source": {"inputType": "text"},
                "pages": [],
                "warnings": [],
            },
            telemetry=ExtractionTelemetry(
                route="pasted_text",
                duration_ms=1,
                external_cost_usd=0,
            ),
        )

    def extract_file(self, source) -> ExtractionResult:
        return self.extract_text(source)


class TransientFailureWorker:
    def __init__(self) -> None:
        self.calls = 0

    def run_available(self, _requested_limit: int) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary database outage")
        return 0


def test_watch_worker_automatically_processes_submitted_job(tmp_path) -> None:
    now = datetime(2026, 7, 30, tzinfo=UTC)
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    service = ExtractionJobService(store, store, store, clock=lambda: now)
    job = service.create(
        CreateJobCommand(
            owner_id="watch-owner",
            input_mode="text",
            source_text="Revenue increased by 14%.",
            file_name=None,
            file_data=None,
            declared_media_type=None,
            deck_purpose="management-review",
            slide_count=8,
            request_key="watch-test",
        )
    )
    delays: list[float] = []

    def stop_after_result(delay: float) -> bool:
        delays.append(delay)
        return service.get(job.id, "watch-owner").status is JobStatus.SUCCEEDED

    processed = run_watch_loop(
        ExtractionJobWorker(store, SuccessfulExtraction(), clock=lambda: now),
        requested_limit=1,
        poll_interval_seconds=0.5,
        error_backoff_seconds=2,
        wait_for_stop=stop_after_result,
    )

    assert processed == 1
    assert service.get(job.id, "watch-owner").status is JobStatus.SUCCEEDED
    assert delays == [0]


def test_watch_worker_uses_error_backoff_then_idle_polling() -> None:
    worker = TransientFailureWorker()
    delays: list[float] = []

    def stop_after_second_wait(delay: float) -> bool:
        delays.append(delay)
        return len(delays) == 2

    processed = run_watch_loop(
        worker,  # type: ignore[arg-type]
        requested_limit=2,
        poll_interval_seconds=0.75,
        error_backoff_seconds=3,
        wait_for_stop=stop_after_second_wait,
    )

    assert processed == 0
    assert worker.calls == 2
    assert delays == [3, 0.75]
