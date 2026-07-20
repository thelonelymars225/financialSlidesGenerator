from fastapi.testclient import TestClient

from financial_slides_api.main import app

client = TestClient(app)


def test_health_response() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_create_text_job() -> None:
    response = client.post(
        "/api/jobs",
        json={
            "input_mode": "text",
            "source_text": "Revenue increased by 14%.",
            "deck_purpose": "management-review",
            "slide_count": 10,
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
