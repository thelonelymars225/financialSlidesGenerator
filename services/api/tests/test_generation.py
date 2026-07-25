import json
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from financial_slides_api.controllers.generation import generation_service_dependency
from financial_slides_api.domain.jobs import CreateJobCommand
from financial_slides_api.infrastructure.deterministic_analysis import (
    DeterministicAnalysisProvider,
)
from financial_slides_api.infrastructure.node_renderer import (
    NodePresentationRenderer,
    RendererError,
)
from financial_slides_api.infrastructure.sqlite_jobs import SQLiteJobStore
from financial_slides_api.main import app
from financial_slides_api.services.analysis import FinancialAnalysisService
from financial_slides_api.services.generation import SlideGenerationService
from financial_slides_api.services.jobs import ExtractionJobService
from financial_slides_api.worker import ExtractionJobWorker

ROOT = Path(__file__).parents[3]
SLIDE_SCHEMA = ROOT / "packages/contracts/schemas/slide-spec-v0.1.schema.json"
SLIDE_EXAMPLE = ROOT / "packages/contracts/examples/slide-spec-v0.1.json"
OWNER_HEADERS = {"X-Owner-ID": "integration-owner"}


class RecordingRenderer:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls = 0

    def render(self, slide_spec: dict) -> bytes:
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RendererError("temporary renderer failure", retryable=True)
        return b"PK\x03\x04test-presentation"


def generation_fixture(tmp_path, renderer):
    store = SQLiteJobStore(tmp_path / "jobs.sqlite3")
    extraction = ExtractionJobService(store, store, store)
    job = extraction.create(
        CreateJobCommand(
            owner_id="integration-owner",
            input_mode="text",
            source_text="Q2 2026 revenue reached $12.4 million.",
            file_name=None,
            file_data=None,
            declared_media_type=None,
            deck_purpose="management-review",
            slide_count=8,
            request_key="generation-integration",
        )
    )
    assert ExtractionJobWorker(store).run_available() == 1
    service = SlideGenerationService(
        extraction,
        FinancialAnalysisService(DeterministicAnalysisProvider()),
        renderer,
    )
    return service, job


def test_extracted_document_to_preview_and_powerpoint_download(tmp_path) -> None:
    renderer = RecordingRenderer()
    service, extraction_job = generation_fixture(tmp_path, renderer)
    app.dependency_overrides[generation_service_dependency] = lambda: service
    client = TestClient(app)
    try:
        started = client.post(
            f"/api/jobs/{extraction_job.id}/slides",
            headers=OWNER_HEADERS,
            json={"deck_type": "management-review"},
        )
        assert started.status_code == 202
        generation_job = started.json()

        status = client.get(
            f"/api/slide-jobs/{generation_job['id']}",
            headers=OWNER_HEADERS,
        )
        result = client.get(
            f"/api/slide-jobs/{generation_job['id']}/result",
            headers=OWNER_HEADERS,
        )
        artifact = client.get(
            f"/api/slide-jobs/{generation_job['id']}/artifact",
            headers=OWNER_HEADERS,
        )

        assert status.json()["status"] == "succeeded"
        assert status.json()["progress"] == 100
        Draft202012Validator(json.loads(SLIDE_SCHEMA.read_text(encoding="utf-8"))).validate(
            result.json()["slide_spec"]
        )
        assert (
            result.json()["slide_spec"]["slides"][1]["components"][0]["value"]["displayedValue"]
            == "$12.4 million"
        )
        assert artifact.content.startswith(b"PK")
        assert artifact.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        assert renderer.calls == 1
    finally:
        app.dependency_overrides.clear()


def test_typed_render_failure_can_retry_once(tmp_path) -> None:
    renderer = RecordingRenderer(fail_once=True)
    service, extraction_job = generation_fixture(tmp_path, renderer)
    app.dependency_overrides[generation_service_dependency] = lambda: service
    client = TestClient(app)
    try:
        started = client.post(
            f"/api/jobs/{extraction_job.id}/slides",
            headers=OWNER_HEADERS,
            json={"deck_type": "management-review"},
        )
        job_id = started.json()["id"]
        failed = client.get(f"/api/slide-jobs/{job_id}", headers=OWNER_HEADERS)

        assert failed.json()["status"] == "failed"
        assert failed.json()["failure"] == {
            "code": "rendering_failed",
            "message": "temporary renderer failure",
            "retryable": True,
        }
        retried = client.post(
            f"/api/slide-jobs/{job_id}/retry",
            headers=OWNER_HEADERS,
        )
        assert retried.status_code == 200
        succeeded = client.get(f"/api/slide-jobs/{job_id}", headers=OWNER_HEADERS)
        assert succeeded.json()["status"] == "succeeded"
        assert succeeded.json()["attempt_count"] == 2
        assert renderer.calls == 2
    finally:
        app.dependency_overrides.clear()


def test_node_adapter_produces_an_editable_powerpoint_archive(tmp_path) -> None:
    slide_spec = json.loads(SLIDE_EXAMPLE.read_text(encoding="utf-8"))
    artifact = NodePresentationRenderer().render(slide_spec)
    path = tmp_path / "presentation.pptx"
    path.write_bytes(artifact)

    with ZipFile(path) as archive:
        names = set(archive.namelist())
    assert "ppt/presentation.xml" in names
    assert "ppt/slides/slide1.xml" in names
