"""Restart-safe extraction worker entry point."""

import argparse
from collections.abc import Callable
from datetime import UTC, datetime

from financial_slides_api.domain.jobs import (
    Job,
    JobFailure,
    JobStatus,
    mark_succeeded,
    retry_or_fail,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.services.jobs import telemetry_from_extraction
from financial_slides_worker import (
    ExtractionError,
    ExtractionService,
    FileSource,
    TextSource,
)

RETRYABLE_FAILURES = frozenset({"extraction_timeout"})


def retry_delay_seconds(attempt_count: int, base_seconds: float = 1.0) -> float:
    return min(60.0, base_seconds * (2 ** max(0, attempt_count - 1)))


class ExtractionJobWorker:
    def __init__(
        self,
        store: SQLiteJobStore,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run queued extraction jobs.")
    parser.add_argument("--database", default=".data/extraction-jobs.sqlite3")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    worker = ExtractionJobWorker(SQLiteJobStore(args.database))
    worker.run_available(args.limit)


if __name__ == "__main__":
    main()
