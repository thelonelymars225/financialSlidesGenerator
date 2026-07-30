"""Restart-safe extraction worker entry point."""

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
import logging
import signal
from threading import Event

from financial_slides_api.domain.jobs import (
    Job,
    JobFailure,
    JobStatus,
    mark_succeeded,
    retry_or_fail,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.ports.jobs import JobStore
from financial_slides_api.services.jobs import get_job_store, telemetry_from_extraction
from financial_slides_worker import (
    ExtractionError,
    ExtractionService,
    FileSource,
    TextSource,
)

RETRYABLE_FAILURES = frozenset({"extraction_timeout"})
LOGGER = logging.getLogger(__name__)


def retry_delay_seconds(attempt_count: int, base_seconds: float = 1.0) -> float:
    return min(60.0, base_seconds * (2 ** max(0, attempt_count - 1)))


class ExtractionJobWorker:
    def __init__(
        self,
        store: JobStore,
        extraction: ExtractionService | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_jobs_per_run: int = 4,
        lease_seconds: float = 300,
    ) -> None:
        if max_jobs_per_run < 1:
            raise ValueError("max_jobs_per_run must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._store = store
        self._extraction = extraction or ExtractionService()
        self._clock = clock
        self._max_jobs_per_run = max_jobs_per_run
        self._lease_seconds = lease_seconds

    def run_available(self, requested_limit: int | None = None) -> int:
        self._store.recover_stale(self._clock(), self._lease_seconds)
        limit = self._max_jobs_per_run
        if requested_limit is not None:
            limit = max(0, min(requested_limit, self._max_jobs_per_run))
        processed = 0
        while processed < limit:
            job = self._store.claim_next(self._clock())
            if job is None:
                break
            self._run(job)
            processed += 1
        return processed

    def _run(self, job: Job) -> None:
        latest = self._store.get(job.id, job.owner_id)
        if latest is None or latest.status is JobStatus.CANCELLED:
            return
        source = self._store.get_source(job.id)
        try:
            if source.input_mode == "text":
                result = self._extraction.extract_text(TextSource(text=source.source_text or ""))
            else:
                result = self._extraction.extract_file(
                    FileSource(
                        data=source.file_data or b"",
                        file_name=source.file_name or "source",
                        declared_media_type=source.declared_media_type,
                    )
                )

            latest = self._store.get(job.id, job.owner_id)
            if latest is None or latest.status is JobStatus.CANCELLED:
                return
            self._store.put_result(job.id, result.document)
            self._store.save(
                mark_succeeded(
                    job,
                    telemetry_from_extraction(result, job.attempt_count),
                    self._clock(),
                )
            )
        except ExtractionError as error:
            self._record_failure(
                job,
                JobFailure(code=error.code, message=error.message),
                error.code in RETRYABLE_FAILURES,
            )
        except Exception:
            self._record_failure(
                job,
                JobFailure(
                    code="worker_failure",
                    message="Extraction failed unexpectedly. Retry may be attempted.",
                ),
                True,
            )

    def _record_failure(self, job: Job, failure: JobFailure, retryable: bool) -> None:
        self._store.save(
            retry_or_fail(
                job,
                failure,
                retryable=retryable,
                retry_delay_seconds=retry_delay_seconds(job.attempt_count),
                now=self._clock(),
            )
        )


def run_watch_loop(
    worker: ExtractionJobWorker,
    *,
    requested_limit: int,
    poll_interval_seconds: float,
    error_backoff_seconds: float,
    wait_for_stop: Callable[[float], bool],
) -> int:
    if requested_limit < 1:
        raise ValueError("requested_limit must be positive")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")
    if error_backoff_seconds <= 0:
        raise ValueError("error_backoff_seconds must be positive")

    processed_total = 0
    while True:
        try:
            processed = worker.run_available(requested_limit)
        except Exception:
            LOGGER.error(
                "Worker batch failed; retrying after %.1f seconds.",
                error_backoff_seconds,
            )
            delay = error_backoff_seconds
        else:
            processed_total += processed
            delay = 0 if processed else poll_interval_seconds

        if wait_for_stop(delay):
            return processed_total


def _stop_event() -> Event:
    stop = Event()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return stop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run queued extraction jobs.")
    parser.add_argument("--database")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep polling for queued jobs until the process receives SIGINT or SIGTERM.",
    )
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--error-backoff-seconds", type=float, default=5.0)
    args = parser.parse_args()
    store = SQLiteJobStore(args.database) if args.database else get_job_store()
    worker = ExtractionJobWorker(store)
    if args.watch:
        run_watch_loop(
            worker,
            requested_limit=args.limit,
            poll_interval_seconds=args.poll_interval_seconds,
            error_backoff_seconds=args.error_backoff_seconds,
            wait_for_stop=_stop_event().wait,
        )
    else:
        worker.run_available(args.limit)


if __name__ == "__main__":
    main()
