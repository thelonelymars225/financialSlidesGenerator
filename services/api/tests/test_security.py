from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from financial_slides_api.domain.jobs import Job, JobStatus
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.main import create_app
from financial_slides_api.quotas import require_job_submission_quota
from financial_slides_api.security import (
    RequestIdentity,
    SecuritySettings,
    request_identity,
    validate_security_configuration,
)


def production_settings() -> SecuritySettings:
    return SecuritySettings(
        environment="production",
        auth_required=True,
        supabase_url="https://project.supabase.co",
        jwt_issuer="https://project.supabase.co/auth/v1",
        jwt_audience="authenticated",
        database_url="postgresql://database.invalid/app?sslmode=require",
    )


def test_production_configuration_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="SUPABASE_URL, DATABASE_URL"):
        validate_security_configuration({"APP_ENV": "production"})

    with pytest.raises(RuntimeError, match="FINANCIAL_SLIDES_STORE=postgres"):
        validate_security_configuration(
            {
                "APP_ENV": "production",
                "SUPABASE_URL": "https://project.supabase.co",
                "SUPABASE_SECRET_KEY": "secret",
                "DATABASE_URL": "postgresql://database.invalid/app?sslmode=require",
                "CORS_ALLOWED_ORIGINS": "https://app.example.com",
                "WORKFLOW_BACKEND": "temporal",
            }
        )


def test_production_rejects_legacy_owner_header_and_missing_bearer() -> None:
    with pytest.raises(HTTPException) as legacy:
        request_identity(
            authorization=None,
            organization_id=str(uuid4()),
            legacy_owner_id="spoofed-owner",
            settings=production_settings(),
        )
    assert legacy.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        request_identity(
            authorization=None,
            organization_id=str(uuid4()),
            legacy_owner_id=None,
            settings=production_settings(),
        )
    assert missing.value.status_code == 401


def test_verified_token_is_still_scoped_by_database_membership(monkeypatch) -> None:
    user_id = str(uuid4())
    organization_id = str(uuid4())

    class Verifier:
        def verify(self, token: str) -> dict:
            assert token == "access-token"
            return {"sub": user_id, "aal": "aal2"}

    class Memberships:
        def role_for(self, candidate_user: str, candidate_organization: str) -> str:
            assert candidate_user == user_id
            assert candidate_organization == organization_id
            return "admin"

    monkeypatch.setattr(
        "financial_slides_api.security.get_jwt_verifier", lambda: Verifier()
    )
    monkeypatch.setattr(
        "financial_slides_api.security.get_membership_authorizer", lambda: Memberships()
    )

    identity = request_identity(
        authorization="Bearer access-token",
        organization_id=organization_id,
        legacy_owner_id=None,
        settings=production_settings(),
    )

    assert identity.user_id == user_id
    assert identity.organization_id == organization_id
    assert identity.role == "admin"
    assert identity.can_manage


def test_request_limit_and_security_headers() -> None:
    client = TestClient(create_app({"APP_ENV": "development", "API_MAX_BODY_BYTES": "1024"}))
    response = client.post(
        "/api/jobs",
        json={
            "input_mode": "text",
            "source_text": "x" * 2000,
            "deck_purpose": "management-review",
            "slide_count": 8,
        },
    )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    health = client.get("/health")
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"


class RejectQuota:
    def consume(self, organization_id: str, quota_name: str, limit: int) -> bool:
        assert organization_id == "organization-1"
        assert quota_name == "job_submissions"
        assert limit == 60
        return False


def test_submission_quota_returns_retryable_429(monkeypatch) -> None:
    monkeypatch.delenv("JOB_SUBMISSIONS_PER_ORG_HOUR", raising=False)
    identity = RequestIdentity("user-1", "organization-1", "member", "aal1", True)
    with pytest.raises(HTTPException) as rejected:
        require_job_submission_quota(identity, RejectQuota())
    assert rejected.value.status_code == 429
    assert rejected.value.headers == {"Retry-After": "3600"}


def sample_job() -> Job:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return Job(
        id=str(uuid4()),
        owner_id="organization-1",
        organization_id="organization-1",
        created_by=str(uuid4()),
        request_key="key-1",
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


def test_sqlite_optimistic_concurrency_rejects_stale_writes(tmp_path) -> None:
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    original = store.create(sample_job())
    saved = store.save(original)
    assert saved.state_version == 1
    with pytest.raises(RuntimeError, match="changed concurrently"):
        store.save(original)
