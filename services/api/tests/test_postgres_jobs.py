from datetime import UTC, datetime
from pathlib import Path

import pytest

from financial_slides_api.domain.jobs import Job, JobStatus
from financial_slides_api.infrastructure.job_records import job_to_record, record_to_job
from financial_slides_api.infrastructure.memory_jobs import InMemoryJobStore
from financial_slides_api.infrastructure.postgres_jobs import (
    CLAIM_NEXT_SQL,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.services.jobs import configured_job_store


def sample_job() -> Job:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    return Job(
        id="43a9db25-06c4-4af3-8c69-74e2049a9d2e",
        owner_id="owner-1",
        request_key="request-1",
        source_hash="sha256:abc",
        input_mode="text",
        file_name=None,
        declared_media_type=None,
        deck_purpose="management-review",
        slide_count=8,
        status=JobStatus.QUEUED,
        created_at=now,
        updated_at=now,
        available_at=now,
    )


def test_persistence_record_round_trip() -> None:
    job = sample_job()

    restored = record_to_job(job_to_record(job))

    assert restored == job


def test_postgres_claim_is_atomic_for_multiple_workers() -> None:
    normalized = " ".join(CLAIM_NEXT_SQL.lower().split())

    assert "for update skip locked" in normalized
    assert "where status = 'queued'" in normalized
    assert "order by available_at, created_at" in normalized


def test_store_configuration_defaults_to_memory(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FINANCIAL_SLIDES_STORE", raising=False)

    assert isinstance(configured_job_store(), InMemoryJobStore)


def test_database_url_does_not_implicitly_enable_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/database")
    monkeypatch.delenv("FINANCIAL_SLIDES_STORE", raising=False)

    assert isinstance(configured_job_store(), InMemoryJobStore)


def test_explicit_sqlite_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FINANCIAL_SLIDES_STORE", "sqlite")
    monkeypatch.setenv("FINANCIAL_SLIDES_JOB_DB", str(tmp_path / "jobs.sqlite3"))

    assert isinstance(configured_job_store(), SQLiteJobStore)


def test_explicit_postgres_requires_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FINANCIAL_SLIDES_STORE", "postgres")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        configured_job_store()


def test_migration_keeps_data_private_and_buckets_restricted() -> None:
    migrations = "\n".join(
        path.read_text() for path in sorted(Path("supabase/migrations").glob("*.sql"))
    )

    assert "create schema if not exists financial_slides" in migrations
    assert "enable row level security" in migrations
    assert "revoke all on all tables" in migrations
    assert migrations.count('create policy "deny direct client access"') == 3
    assert "'source-documents'" in migrations
    assert "'generated-presentations'" in migrations
    assert migrations.count("\n        false,") == 2
