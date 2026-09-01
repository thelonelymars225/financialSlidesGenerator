import asyncio
import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

import pytest
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
from financial_slides_api.services.generation import (
    SlideGenerationService,
    _analysis_provider_for_generation,
    build_slide_spec,
)
from financial_slides_api.services.jobs import ExtractionJobService
from financial_slides_api.worker import ExtractionJobWorker

ROOT = Path(__file__).parents[3]
SLIDE_SCHEMA = ROOT / "packages/contracts/schemas/slide-spec-v0.1.schema.json"
SLIDE_EXAMPLE = ROOT / "packages/contracts/examples/slide-spec-v0.1.json"
ANALYSIS_EXAMPLE = ROOT / "packages/contracts/examples/analysis-v0.2.json"
PREFLIGHT_CLI = ROOT / "packages/presentation-harness/scripts/preflight-deck.mjs"
OWNER_HEADERS = {"X-Owner-ID": "integration-owner"}


def test_api_docker_context_excludes_local_environment_files() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "!.env.example" in dockerignore


def test_generation_fails_closed_to_deterministic_without_retention_assertion() -> None:
    provider = _analysis_provider_for_generation(
        {
            "MODEL_PROVIDER": "deepseek",
            "MODEL_API_KEY": "test-secret",
        }
    )

    assert provider.name == "deterministic"


def test_production_rejects_deterministic_or_incomplete_hosted_configuration() -> None:
    with pytest.raises(RuntimeError, match="hosted MODEL_PROVIDER"):
        _analysis_provider_for_generation({"APP_ENV": "production"})

    with pytest.raises(RuntimeError, match="MODEL_DATA_RETENTION_DISABLED"):
        _analysis_provider_for_generation(
            {
                "APP_ENV": "production",
                "MODEL_PROVIDER": "deepseek",
                "MODEL_API_KEY": "test-secret",
            }
        )


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
    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, request, validation_feedback) -> ProviderAnalysis:
        self.calls += 1
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
            json={"deck_type": "management-review", "request_key": "automatic-flow"},
        )
        assert started.status_code == 202
        generation_job = started.json()
        assert generation_job["slide_count"] == 8
        assert generation_job["density"] == "balanced"

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
        assert result.json()["job"]["analysis"] == {
            "mode": "deterministic",
            "provider": "deterministic",
            "model": "fixture-v1",
            "fallback_used": False,
            "provider_calls": 1,
            "external_cost_usd": 0.0,
        }
        Draft202012Validator(json.loads(SLIDE_SCHEMA.read_text(encoding="utf-8"))).validate(
            result.json()["slide_spec"]
        )
        assert len(result.json()["slide_spec"]["slides"]) == 8
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
            json={"deck_type": "management-review", "request_key": "rich-flow"},
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
            json={"deck_type": "management-review", "request_key": "retry-flow"},
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


def test_start_is_idempotent_for_the_same_automatic_request(tmp_path) -> None:
    renderer = RecordingRenderer()
    service, extraction_job = generation_fixture(tmp_path, renderer)

    first = service.start(
        extraction_job.id,
        extraction_job.owner_id,
        "management-review",
        "auto:stable",
    )
    repeated = service.start(
        extraction_job.id,
        extraction_job.owner_id,
        "management-review",
        "auto:stable",
    )
    asyncio.run(service.run(first.id))
    asyncio.run(service.run(repeated.id))

    assert repeated.id == first.id
    assert renderer.calls == 1


def test_density_is_part_of_generation_idempotency(tmp_path) -> None:
    service, extraction_job = generation_fixture(tmp_path, RecordingRenderer())

    concise = service.start(
        extraction_job.id,
        extraction_job.owner_id,
        "management-review",
        "auto:density",
        density_profile="concise",
    )
    detailed = service.start(
        extraction_job.id,
        extraction_job.owner_id,
        "management-review",
        "auto:density",
        density_profile="detailed",
    )

    assert concise.id != detailed.id
    assert concise.density_profile.value == "concise"
    assert detailed.density_profile.value == "detailed"


def test_generation_rejects_an_unknown_density(tmp_path) -> None:
    renderer = RecordingRenderer()
    service, extraction_job = generation_fixture(tmp_path, renderer)
    app.dependency_overrides[generation_service_dependency] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            f"/api/jobs/{extraction_job.id}/slides",
            headers=OWNER_HEADERS,
            json={"deck_type": "management-review", "density": "maximum"},
        )

        assert response.status_code == 422
        assert renderer.calls == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("requested_count", [4, 8, 10])
def test_density_changes_detail_without_changing_slide_count(requested_count: int) -> None:
    analysis = json.loads(ANALYSIS_EXAMPLE.read_text(encoding="utf-8"))

    concise = build_slide_spec(
        analysis, "management-review", requested_count, density="concise"
    )
    balanced = build_slide_spec(analysis, "management-review", requested_count)
    detailed = build_slide_spec(
        analysis, "management-review", requested_count, density="detailed"
    )

    for spec in (concise, balanced, detailed):
        assert spec["requestedSlideCount"] == requested_count
        assert len(spec["slides"]) == requested_count
    assert concise["densityConstraints"]["speakerNotesDepth"] == "minimal"
    assert balanced["densityConstraints"]["speakerNotesDepth"] == "standard"
    assert detailed["densityConstraints"]["speakerNotesDepth"] == "rich"
    note_lengths = [
        sum(len(slide.get("speakerNotes", "")) for slide in spec["slides"])
        for spec in (concise, balanced, detailed)
    ]
    assert note_lengths[0] < note_lengths[1] < note_lengths[2]
    assert not any(
        component["type"] in {"table", "chart"}
        for slide in concise["slides"]
        for component in slide["components"]
    )
    assert any(
        component["type"] == "chart"
        for slide in balanced["slides"]
        for component in slide["components"]
    ) == (requested_count >= 4)


def test_sparse_analysis_is_filled_to_the_requested_count_with_grounded_content() -> None:
    analysis = json.loads(ANALYSIS_EXAMPLE.read_text(encoding="utf-8"))
    analysis["metrics"] = analysis["metrics"][:1]
    analysis["findings"] = []
    analysis["executiveSummary"] = analysis["executiveSummary"][:1]
    analysis["slideIntents"] = analysis["slideIntents"][:1]
    analysis["slideIntents"][0]["metricIds"] = [analysis["metrics"][0]["id"]]
    analysis["slideIntents"][0]["findingIds"] = []

    spec = build_slide_spec(analysis, "management-review", 10, density="detailed")

    assert len(spec["slides"]) == 10
    assert all(slide["components"] for slide in spec["slides"])
    assert any("-copy-" in slide["id"] for slide in spec["slides"])


def test_density_caps_table_rows() -> None:
    analysis = json.loads(ANALYSIS_EXAMPLE.read_text(encoding="utf-8"))
    source = analysis["metrics"][0]
    metrics = []
    for index in range(14):
        metric = deepcopy(source)
        metric["id"] = f"revenue-period-{index + 1}"
        metric["period"]["label"] = f"Period {index + 1}"
        metrics.append(metric)
    analysis["metrics"] = metrics
    analysis["slideIntents"][0]["metricIds"] = [metric["id"] for metric in metrics]

    spec = build_slide_spec(analysis, "management-review", 10, density="balanced")
    table = next(
        component
        for slide in spec["slides"]
        for component in slide["components"]
        if component["type"] == "table"
    )
    assert len(table["rows"]) == 8


def test_render_retry_reuses_successful_analysis(tmp_path) -> None:
    store = SQLiteJobStore(tmp_path / "stage-aware.sqlite3")
    extraction = ExtractionJobService(store, store, store)
    source_job = extraction.create(
        CreateJobCommand(
            owner_id="integration-owner",
            input_mode="text",
            source_text="Quarterly revenue\nQ1 2026 | $10.0m\nQ2 2026 | $12.4m",
            file_name=None,
            file_data=None,
            declared_media_type=None,
            deck_purpose="management-review",
            slide_count=4,
            request_key="stage-aware-source",
        )
    )
    assert ExtractionJobWorker(store).run_available() == 1
    provider = FinancialReportProvider()
    renderer = RecordingRenderer(fail_once=True)
    service = SlideGenerationService(
        extraction,
        FinancialAnalysisService(provider),
        renderer,
    )
    generation_job = service.start(
        source_job.id,
        source_job.owner_id,
        "management-review",
        "stage-aware-generation",
    )

    asyncio.run(service.run(generation_job.id))
    failed = service.get(generation_job.id, source_job.owner_id)
    assert failed.status.value == "failed"
    assert failed.slide_spec is not None
    service.retry(generation_job.id, source_job.owner_id)
    asyncio.run(service.run(generation_job.id))

    succeeded = service.get(generation_job.id, source_job.owner_id)
    assert succeeded.status.value == "succeeded"
    assert succeeded.slide_count == 4
    assert succeeded.density_profile.value == "balanced"
    assert succeeded.slide_spec["requestedSlideCount"] == 4
    assert len(succeeded.slide_spec["slides"]) == 4
    assert succeeded.analysis_telemetry is not None
    assert provider.calls == 1
    assert renderer.calls == 2


def test_node_adapter_produces_an_editable_powerpoint_archive(tmp_path) -> None:
    slide_spec = json.loads(SLIDE_EXAMPLE.read_text(encoding="utf-8"))
    artifact = NodePresentationRenderer().render(slide_spec)
    path = tmp_path / "presentation.pptx"
    path.write_bytes(artifact)

    with ZipFile(path) as archive:
        names = set(archive.namelist())
    assert "ppt/presentation.xml" in names
    assert "ppt/slides/slide1.xml" in names
