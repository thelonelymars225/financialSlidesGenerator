import logging
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from financial_slides_api.main import app, cors_origins_from_environment, create_app

client = TestClient(app)


def test_health_response() -> None:
    ready_response = TestClient(create_app({})).get("/health/ready")
    alias_response = TestClient(create_app({})).get("/health")

    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "status": "ok",
        "service": "api",
        "analysis_provider": "deterministic",
        "analysis_model": "fixture-v1",
        "analysis_ready": True,
        "storage_adapter": "memory",
        "storage_ready": True,
    }
    assert alias_response.status_code == ready_response.status_code
    assert alias_response.json() == ready_response.json()


def test_production_health_fails_when_hosted_provider_is_missing() -> None:
    production_client = TestClient(create_app({"APP_ENV": "production"}))

    response = production_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "api",
        "analysis_provider": "deterministic",
        "analysis_model": "fixture-v1",
        "analysis_ready": False,
        "storage_adapter": "memory",
        "storage_ready": True,
    }


def test_readiness_fails_when_configured_storage_is_invalid() -> None:
    response = TestClient(
        create_app(
            {
                "FINANCIAL_SLIDES_STORE": "postgres",
                "MODEL_PROVIDER": "deterministic",
            }
        )
    ).get("/health/ready")

    assert response.status_code == 503
    assert response.json()["analysis_ready"] is True
    assert response.json()["storage_adapter"] == "postgres"
    assert response.json()["storage_ready"] is False


def test_liveness_does_not_depend_on_readiness() -> None:
    response = TestClient(
        create_app(
            {
                "APP_ENV": "production",
                "FINANCIAL_SLIDES_STORE": "postgres",
            }
        )
    ).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_request_id_is_created_and_propagated() -> None:
    response = TestClient(create_app({})).get("/health/live")

    assert UUID(response.headers["X-Request-ID"])


def test_valid_request_id_is_preserved_and_logged_on_failure(caplog) -> None:
    caplog.set_level(logging.ERROR)
    response = TestClient(create_app({})).get(
        "/missing",
        headers={"X-Request-ID": "frontend-request-123"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "frontend-request-123"
    failure = next(record for record in caplog.records if record.message == "API request failed")
    assert failure.request_id == "frontend-request-123"
    assert failure.method == "GET"
    assert failure.path == "/missing"


def test_reads_unique_cors_origins_from_environment() -> None:
    assert cors_origins_from_environment(
        {
            "CORS_ALLOWED_ORIGINS": (
                "https://financial-slides.pages.dev/, https://app.example.com, "
                "https://app.example.com"
            )
        }
    ) == ["https://financial-slides.pages.dev", "https://app.example.com"]


def test_rejects_invalid_cors_origin() -> None:
    with pytest.raises(ValueError, match="invalid CORS origin"):
        cors_origins_from_environment({"CORS_ALLOWED_ORIGINS": "financial-slides.pages.dev"})


def test_create_text_job() -> None:
    response = client.post(
        "/api/jobs",
        json={
            "input_mode": "text",
            "source_text": "Revenue increased by 14%.",
            "deck_purpose": "management-review",
            "slide_count": 10,
            "request_key": f"health-test-create-text-job-{uuid4()}",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_rejects_text_job_without_source() -> None:
    response = client.post(
        "/api/jobs",
        json={
            "input_mode": "text",
            "deck_purpose": "management-review",
            "slide_count": 10,
        },
    )
    assert response.status_code == 422
