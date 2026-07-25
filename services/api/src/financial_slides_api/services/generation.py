"""Application orchestration for analysis, slide compilation, and rendering."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from threading import RLock
from typing import Any
from uuid import uuid4

from financial_slides_api.domain.analysis import AnalysisError
from financial_slides_api.domain.generation import (
    GenerationConflictError,
    GenerationFailure,
    GenerationJob,
    GenerationNotFoundError,
    GenerationNotReadyError,
    GenerationStatus,
    transition,
)
from financial_slides_api.infrastructure.hosted_analysis import (
    analysis_provider_from_environment,
)
from financial_slides_api.infrastructure.node_renderer import (
    NodePresentationRenderer,
    RendererError,
)
from financial_slides_api.ports.generation import PresentationArtifactRenderer
from financial_slides_api.services.analysis import FinancialAnalysisService
from financial_slides_api.services.jobs import ExtractionJobService, get_job_service

DECK_TITLES = {
    "management-review": "Management Review",
    "board-update": "Board Update",
    "investor-summary": "Investor Summary",
}


def _sources(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in item.items()
            if key in {"documentId", "pageNumber", "blockId", "quote"}
        }
        for item in evidence
    ]


def build_slide_spec(analysis: dict[str, Any], deck_type: str) -> dict[str, Any]:
    """Map validated analysis to the narrow, approved slide contract."""

    slides: list[dict[str, Any]] = [
        {
            "id": "slide-title",
            "order": 1,
            "layoutId": "title",
            "title": DECK_TITLES[deck_type],
            "components": [
                {
                    "id": "title-summary",
                    "type": "text",
                    "region": "body",
                    "sources": [],
                    "text": analysis["executiveSummary"][0],
                    "variant": "callout",
                }
            ],
        }
    ]
    metrics = {metric["id"]: metric for metric in analysis["metrics"]}
    findings = {finding["id"]: finding for finding in analysis["findings"]}

    for intent in analysis["slideIntents"]:
        metric = next(
            (metrics[metric_id] for metric_id in intent["metricIds"] if metric_id in metrics),
            None,
        )
        finding = next(
            (findings[finding_id] for finding_id in intent["findingIds"] if finding_id in findings),
            None,
        )
        if metric:
            component = {
                "id": f"component-{metric['id']}",
                "type": "metric",
                "region": "primary",
                "sources": _sources(metric["evidence"]),
                "metricId": metric["id"],
                "label": metric["name"],
                "value": {
                    key: metric[key]
                    for key in ("displayedValue", "value", "normalizedValue", "unit", "period")
                },
            }
            layout = "kpi-grid"
        elif finding:
            component = {
                "id": f"component-{finding['id']}",
                "type": "insight",
                "region": "body",
                "sources": _sources(finding["evidence"]),
                "findingId": finding["id"],
                "statement": finding["statement"],
                "emphasis": "neutral",
            }
            layout = "insight"
        else:
            continue
        slides.append(
            {
                "id": f"slide-{intent['id']}",
                "order": len(slides) + 1,
                "layoutId": layout,
                "title": intent["title"],
                "components": [component],
            }
        )

    if len(slides) == 1:
        raise ValueError("analysis did not contain a renderable slide intent")
    return {
        "schemaVersion": "0.1",
        "deckId": f"deck-{analysis['analysisId']}",
        "sourceAnalysisId": analysis["analysisId"],
        "sourceDocumentIds": analysis["sourceDocumentIds"],
        "title": DECK_TITLES[deck_type],
        "subtitle": "Source-grounded financial presentation",
        "audience": DECK_TITLES[deck_type],
        "themeId": "theme-corporate-default",
        "slides": slides,
    }


class SlideGenerationService:
    def __init__(
        self,
        extraction: ExtractionJobService,
        analysis: FinancialAnalysisService,
        renderer: PresentationArtifactRenderer,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_attempts: int = 2,
    ) -> None:
        self._extraction = extraction
        self._analysis = analysis
        self._renderer = renderer
        self._clock = clock
        self._max_attempts = max_attempts
        self._jobs: dict[str, GenerationJob] = {}
        self._lock = RLock()

    def start(self, extraction_job_id: str, owner_id: str, deck_type: str) -> GenerationJob:
        extraction_job, _ = self._extraction.result(extraction_job_id, owner_id)
        if deck_type != extraction_job.deck_purpose:
            raise GenerationConflictError("deck type must match the extraction request")
        now = self._clock()
        job = GenerationJob(
            id=str(uuid4()),
            extraction_job_id=extraction_job_id,
            owner_id=owner_id,
            deck_type=deck_type,
            status=GenerationStatus.QUEUED,
            progress=0,
            attempt_count=0,
            max_attempts=self._max_attempts,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str, owner_id: str) -> GenerationJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise GenerationNotFoundError("slide-generation job was not found")
        return job

    def _save(self, job: GenerationJob) -> GenerationJob:
        with self._lock:
            self._jobs[job.id] = job
        return job

    async def run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status is not GenerationStatus.QUEUED:
                return
            job = replace(job, attempt_count=job.attempt_count + 1)
            self._jobs[job.id] = transition(job, GenerationStatus.ANALYZING, 25, self._clock())
        try:
            _, document = self._extraction.result(job.extraction_job_id, job.owner_id)
            analysis = await self._analysis.analyze(document)
            slide_spec = build_slide_spec(analysis.analysis, job.deck_type)
            self._save(
                transition(
                    replace(job, slide_spec=slide_spec),
                    GenerationStatus.RENDERING,
                    75,
                    self._clock(),
                )
            )
            artifact = await asyncio.to_thread(self._renderer.render, slide_spec)
            self._save(
                replace(
                    job,
                    status=GenerationStatus.SUCCEEDED,
                    progress=100,
                    updated_at=self._clock(),
                    slide_spec=slide_spec,
                    artifact=artifact,
                    failure=None,
                )
            )
        except AnalysisError as error:
            self._fail(job, f"analysis_{error.code.value}", error.message, error.retryable)
        except RendererError as error:
            self._fail(job, "rendering_failed", str(error), error.retryable)
        except (ValueError, KeyError, IndexError):
            self._fail(job, "compilation_failed", "slide compilation failed", False)
        except Exception:
            self._fail(job, "rendering_failed", "presentation rendering failed", True)

    def _fail(self, job: GenerationJob, code: str, message: str, retryable: bool) -> None:
        self._save(
            replace(
                job,
                status=GenerationStatus.FAILED,
                progress=100,
                updated_at=self._clock(),
                failure=GenerationFailure(code, message, retryable),
            )
        )

    def retry(self, job_id: str, owner_id: str) -> GenerationJob:
        job = self.get(job_id, owner_id)
        if (
            job.status is not GenerationStatus.FAILED
            or not job.failure
            or not job.failure.retryable
            or job.attempt_count >= job.max_attempts
        ):
            raise GenerationConflictError("slide-generation job cannot be retried")
        return self._save(
            replace(
                job,
                status=GenerationStatus.QUEUED,
                progress=0,
                updated_at=self._clock(),
                failure=None,
                artifact=None,
            )
        )

    def result(self, job_id: str, owner_id: str) -> GenerationJob:
        job = self.get(job_id, owner_id)
        if job.status is not GenerationStatus.SUCCEEDED or not job.slide_spec:
            raise GenerationNotReadyError("slide-generation result is not available")
        return job

    def artifact(self, job_id: str, owner_id: str) -> bytes:
        job = self.result(job_id, owner_id)
        if not job.artifact:
            raise GenerationNotReadyError("PowerPoint artifact is not available")
        return job.artifact


@lru_cache(maxsize=1)
def get_generation_service() -> SlideGenerationService:
    return SlideGenerationService(
        get_job_service(),
        FinancialAnalysisService(analysis_provider_from_environment()),
        NodePresentationRenderer(),
    )
