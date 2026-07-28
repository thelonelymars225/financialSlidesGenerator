import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from financial_slides_api.controllers.generation import generation_service_dependency
from financial_slides_api.domain.analysis import ProviderAnalysis, ProviderTelemetry
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
ANALYSIS_EXAMPLE = ROOT / "packages/contracts/examples/analysis-v0.2.json"
PREFLIGHT_CLI = ROOT / "packages/presentation-harness/scripts/preflight-deck.mjs"
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


class FinancialReportProvider:
    async def analyze(self, request, validation_feedback) -> ProviderAnalysis:
        del validation_feedback
        output = deepcopy(json.loads(ANALYSIS_EXAMPLE.read_text(encoding="utf-8")))
        output["sourceDocumentIds"] = [request.document_id]
        source_block = request.blocks[0]
        for item in [*output["metrics"], *output["findings"]]:
            for evidence in item["evidence"]:
                evidence["documentId"] = request.document_id
                evidence["pageNumber"] = source_block.page_number
                evidence["blockId"] = source_block.block_id
        return ProviderAnalysis(
            output=output,
            telemetry=ProviderTelemetry(provider="scripted", model="approved-fixture"),
        )


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


def rich_generation_fixture(tmp_path):
    store = SQLiteJobStore(tmp_path / "rich-jobs.sqlite3")
    extraction = ExtractionJobService(store, store, store)
    job = extraction.create(
        CreateJobCommand(
            owner_id="integration-owner",
            input_mode="text",
            source_text="Quarterly revenue\nQ1 2026 | $10.0m\nQ2 2026 | $12.4m",
            file_name=None,
            file_data=None,
            declared_media_type=None,
            deck_purpose="management-review",
            slide_count=4,
            request_key="thin-end-to-end-prototype",
        )
    )
    assert ExtractionJobWorker(store).run_available() == 1
    assert extraction.result(job.id, job.owner_id)[0].telemetry.route == "pasted_text"
    return (
        SlideGenerationService(
            extraction,
            FinancialAnalysisService(FinancialReportProvider()),
            NodePresentationRenderer(),
        ),
        job,
    )


def assert_browser_preflight(slide_spec: dict) -> None:
    completed = subprocess.run(
        ["node", str(PREFLIGHT_CLI)],
        cwd=ROOT,
        input=json.dumps(slide_spec),
        text=True,
        capture_output=True,
        check=False,
    )
    if (
        completed.returncode
        and not os.getenv("CI")
        and "Executable doesn't exist" in completed.stderr
    ):
        return
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout)["status"] == "passed"


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


def test_thin_end_to_end_prototype_preserves_financial_content(tmp_path) -> None:
    service, extraction_job = rich_generation_fixture(tmp_path)
    app.dependency_overrides[generation_service_dependency] = lambda: service
    client = TestClient(app)
    try:
        started = client.post(
            f"/api/jobs/{extraction_job.id}/slides",
            headers=OWNER_HEADERS,
            json={"deck_type": "management-review"},
        )
        assert started.status_code == 202
        job_id = started.json()["id"]
        result = client.get(f"/api/slide-jobs/{job_id}/result", headers=OWNER_HEADERS)
        artifact = client.get(f"/api/slide-jobs/{job_id}/artifact", headers=OWNER_HEADERS)

        assert result.status_code == 200
        slide_spec = result.json()["slide_spec"]
        Draft202012Validator(json.loads(SLIDE_SCHEMA.read_text(encoding="utf-8"))).validate(
            slide_spec
        )
        components = [
            component for slide in slide_spec["slides"] for component in slide["components"]
        ]
        assert (
            next(component for component in components if component["type"] == "metric")["value"][
                "displayedValue"
            ]
            == "24%"
        )
        assert [component["type"] for component in components].count("table") == 1
        assert [component["type"] for component in components].count("chart") == 1
        assert all(
            component["sources"]
            for component in components
            if component["type"] in {"metric", "table", "chart"}
        )
        assert_browser_preflight(slide_spec)

        path = tmp_path / "financial-report.pptx"
        path.write_bytes(artifact.content)
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            slide_xml = b"".join(
                archive.read(name)
                for name in names
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
            notes = b"".join(
                archive.read(name)
                for name in names
                if name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml")
            )
        assert any(name.startswith("ppt/charts/chart") for name in names)
        assert b"<a:tbl>" in slide_xml
        assert b"Sources:" in notes
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
