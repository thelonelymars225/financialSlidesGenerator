"""Application orchestration for analysis, slide compilation, and rendering."""

import asyncio
import os
from collections.abc import Callable
from collections.abc import Mapping
from copy import deepcopy
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
from financial_slides_api.infrastructure.audit import MetadataAuditLogger, NullAuditSink
from financial_slides_api.infrastructure.deterministic_analysis import (
    DeterministicAnalysisProvider,
)
from financial_slides_api.infrastructure.hosted_analysis import (
    analysis_timeout_seconds_from_environment,
    analysis_provider_from_environment,
)
from financial_slides_api.infrastructure.node_renderer import (
    NodePresentationRenderer,
    RendererError,
)
from financial_slides_api.ports.analysis import AnalysisProvider
from financial_slides_api.ports.generation import PresentationArtifactRenderer
from financial_slides_api.ports.privacy import AuditSink
from financial_slides_api.services.analysis import FinancialAnalysisService
from financial_slides_api.services.jobs import ExtractionJobService, get_job_service
from financial_slides_api.services.privacy import RetentionPolicy, get_retention_policy

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


def _unique_sources(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for metric in metrics:
        for source in _sources(metric["evidence"]):
            key = (source["documentId"], source["pageNumber"], source["blockId"])
            unique.setdefault(key, source)
    return list(unique.values())


def _value(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        key: metric[key] for key in ("displayedValue", "value", "normalizedValue", "unit", "period")
    }


def _speaker_notes(sources: list[dict[str, Any]]) -> str:
    citations = (
        f"{source['documentId']} p.{source['pageNumber']} {source['blockId']}" for source in sources
    )
    return f"Sources: {'; '.join(citations)}"


def _trend_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    direct = [metric for metric in metrics if "calculation" not in metric]
    if len(direct) < 2:
        return []
    first = direct[0]
    return [
        metric
        for metric in direct
        if metric["name"] == first["name"] and metric["unit"] == first["unit"]
    ]


def _metric_slide(intent: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any]:
    sources = _sources(metric["evidence"])
    return {
        "layoutId": "kpi-grid",
        "title": intent["title"],
        "speakerNotes": _speaker_notes(sources),
        "components": [
            {
                "id": f"component-{metric['id']}",
                "type": "metric",
                "region": "primary",
                "sources": sources,
                "metricId": metric["id"],
                "label": metric["name"],
                "value": _value(metric),
            }
        ],
    }


def _table_slide(intent: dict[str, Any], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    sources = _unique_sources(metrics)
    return {
        "layoutId": "financial-table",
        "title": f"{intent['title']} — data",
        "speakerNotes": _speaker_notes(sources),
        "components": [
            {
                "id": f"table-{intent['id']}",
                "type": "table",
                "region": "body",
                "sources": sources,
                "columns": ["Period", metrics[0]["name"]],
                "rows": [
                    [
                        {"kind": "text", "text": metric["period"]["label"]},
                        {"kind": "financial", "value": _value(metric)},
                    ]
                    for metric in metrics
                ],
            }
        ],
    }


def _chart_slide(intent: dict[str, Any], metrics: list[dict[str, Any]]) -> dict[str, Any]:
    sources = _unique_sources(metrics)
    return {
        "layoutId": "chart",
        "title": intent["title"],
        "speakerNotes": _speaker_notes(sources),
        "components": [
            {
                "id": f"chart-{intent['id']}",
                "type": "chart",
                "region": "primary",
                "sources": sources,
                "chartType": intent["preferredVisual"],
                "categories": [metric["period"]["label"] for metric in metrics],
                "series": [
                    {
                        "id": f"series-{intent['id']}",
                        "name": metrics[0]["name"],
                        "values": [_value(metric) for metric in metrics],
                    }
                ],
            }
        ],
    }


def _copy_slide(slide: dict[str, Any], copy_number: int) -> dict[str, Any]:
    copied = deepcopy(slide)
    suffix = f"-copy-{copy_number}"

    def make_ids_unique(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "id" and isinstance(item, str):
                    value[key] = f"{item[: 100 - len(suffix)]}{suffix}"
                else:
                    make_ids_unique(item)
        elif isinstance(value, list):
            for item in value:
                make_ids_unique(item)

    make_ids_unique(copied)
    copied["title"] = f"{slide['title']} — detail {copy_number}"[:120]
    return copied


def _fit_slide_count(slides: list[dict[str, Any]], slide_count: int) -> list[dict[str, Any]]:
    if slide_count < 1:
        raise ValueError("slide_count must be positive")
    fitted = slides[:slide_count]
    content = fitted[1:]
    copy_number = 1
    while len(fitted) < slide_count:
        if not content:
            raise ValueError("analysis did not contain enough renderable content")
        source = content[(copy_number - 1) % len(content)]
        fitted.append(_copy_slide(source, copy_number))
        copy_number += 1
    for order, slide in enumerate(fitted, start=1):
        slide["order"] = order
    return fitted


def build_slide_spec(
    analysis: dict[str, Any],
    deck_type: str,
    slide_count: int,
) -> dict[str, Any]:
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
        intent_metrics = [
            metrics[metric_id] for metric_id in intent["metricIds"] if metric_id in metrics
        ]
        metric = next(
            (item for item in intent_metrics if "calculation" in item),
            intent_metrics[0] if intent_metrics else None,
        )
        finding = next(
            (findings[finding_id] for finding_id in intent["findingIds"] if finding_id in findings),
            None,
        )
        if metric:
            compiled = [_metric_slide(intent, metric)]
            trend = _trend_metrics(intent_metrics)
            if len(trend) >= 2 and intent["preferredVisual"] in {"line", "bar", "waterfall"}:
                compiled.extend((_table_slide(intent, trend), _chart_slide(intent, trend)))
        elif finding:
            sources = _sources(finding["evidence"])
            compiled = [
                {
                    "layoutId": "insight",
                    "title": intent["title"],
                    "speakerNotes": _speaker_notes(sources),
                    "components": [
                        {
                            "id": f"component-{finding['id']}",
                            "type": "insight",
                            "region": "body",
                            "sources": sources,
                            "findingId": finding["id"],
                            "statement": finding["statement"],
                            "emphasis": "neutral",
                        }
                    ],
                }
            ]
        else:
            continue
        for index, slide in enumerate(compiled, start=1):
            suffix = f"-{index}" if len(compiled) > 1 else ""
            slides.append(
                {
                    "id": f"slide-{intent['id']}{suffix}",
                    "order": len(slides) + 1,
                    **slide,
                }
            )

    if len(slides) == 1:
        raise ValueError("analysis did not contain a renderable slide intent")

    rendered_metric_ids = {
        component.get("metricId")
        for slide in slides
        for component in slide["components"]
        if component.get("metricId")
    }
    for metric in metrics.values():
        if len(slides) >= slide_count or metric["id"] in rendered_metric_ids:
            continue
        slide = _metric_slide({"title": f"{metric['name']} — detail"}, metric)
        slides.append(
            {
                "id": f"slide-metric-{metric['id']}",
                "order": len(slides) + 1,
                **slide,
            }
        )

    rendered_finding_ids = {
        component.get("findingId")
        for slide in slides
        for component in slide["components"]
        if component.get("findingId")
    }
    for finding in findings.values():
        if len(slides) >= slide_count or finding["id"] in rendered_finding_ids:
            continue
        sources = _sources(finding["evidence"])
        slides.append(
            {
                "id": f"slide-finding-{finding['id']}",
                "order": len(slides) + 1,
                "layoutId": "insight",
                "title": finding["title"],
                "speakerNotes": _speaker_notes(sources),
                "components": [
                    {
                        "id": f"component-finding-{finding['id']}",
                        "type": "insight",
                        "region": "body",
                        "sources": sources,
                        "findingId": finding["id"],
                        "statement": finding["statement"],
                        "emphasis": "neutral",
                    }
                ],
            }
        )

    summary_sources = _unique_sources(list(metrics.values()))[:20]
    for index, summary in enumerate(analysis["executiveSummary"], start=1):
        if len(slides) >= slide_count:
            break
        slides.append(
            {
                "id": f"slide-summary-{index}",
                "order": len(slides) + 1,
                "layoutId": "insight",
                "title": "Executive summary",
                "speakerNotes": _speaker_notes(summary_sources),
                "components": [
                    {
                        "id": f"component-summary-{index}",
                        "type": "text",
                        "region": "body",
                        "sources": summary_sources,
                        "text": summary,
                        "variant": "callout",
                    }
                ],
            }
        )

    slides = _fit_slide_count(slides, slide_count)
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
        policy: RetentionPolicy = RetentionPolicy(),
        audit: AuditSink | None = None,
    ) -> None:
        self._extraction = extraction
        self._analysis = analysis
        self._renderer = renderer
        self._clock = clock
        self._max_attempts = max_attempts
        self._policy = policy
        self._audit = audit or NullAuditSink()
        self._jobs: dict[str, GenerationJob] = {}
        self._request_jobs: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def start(
        self,
        extraction_job_id: str,
        owner_id: str,
        deck_type: str,
        request_key: str,
    ) -> GenerationJob:
        self._purge_expired_outputs()
        extraction_job, _ = self._extraction.result(extraction_job_id, owner_id)
        if deck_type != extraction_job.deck_purpose:
            raise GenerationConflictError("deck type must match the extraction request")
        idempotency_key = (owner_id, extraction_job_id, request_key)
        with self._lock:
            existing_id = self._request_jobs.get(idempotency_key)
            if existing_id:
                return self._jobs[existing_id]
        now = self._clock()
        job = GenerationJob(
            id=str(uuid4()),
            extraction_job_id=extraction_job_id,
            owner_id=owner_id,
            deck_type=deck_type,
            slide_count=extraction_job.slide_count,
            request_key=request_key,
            status=GenerationStatus.QUEUED,
            progress=0,
            attempt_count=0,
            max_attempts=self._max_attempts,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            existing_id = self._request_jobs.get(idempotency_key)
            if existing_id:
                return self._jobs[existing_id]
            self._jobs[job.id] = job
            self._request_jobs[idempotency_key] = job.id
        return job

    def get(self, job_id: str, owner_id: str) -> GenerationJob:
        self._purge_expired_outputs()
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
            next_status = (
                GenerationStatus.RENDERING if job.slide_spec else GenerationStatus.ANALYZING
            )
            next_progress = 75 if job.slide_spec else 25
            job = transition(job, next_status, next_progress, self._clock())
            self._jobs[job.id] = job
        try:
            slide_spec = job.slide_spec
            if slide_spec is None:
                _, document = self._extraction.result(job.extraction_job_id, job.owner_id)
                analysis = await self._analysis.analyze(document)
                slide_spec = build_slide_spec(analysis.analysis, job.deck_type, job.slide_count)
                job = self._save(
                    transition(
                        replace(
                            job,
                            slide_spec=slide_spec,
                            analysis_telemetry=analysis.telemetry,
                        ),
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

    def delete_output(self, job_id: str, owner_id: str) -> int:
        job = self.get(job_id, owner_id)
        if job.status not in {GenerationStatus.SUCCEEDED, GenerationStatus.FAILED}:
            raise GenerationConflictError(
                "slide-generation output cannot be deleted while processing"
            )
        deleted = int(job.slide_spec is not None) + int(job.artifact is not None)
        self._save(
            replace(
                job,
                updated_at=self._clock(),
                slide_spec=None,
                artifact=None,
            )
        )
        self._audit.record(
            "generation_output_deleted",
            job.id,
            owner_id,
            deleted_count=deleted,
        )
        return deleted

    def _purge_expired_outputs(self) -> int:
        cutoff = self._policy.artifact_cutoff(self._clock())
        expired: list[GenerationJob] = []
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.status in {GenerationStatus.SUCCEEDED, GenerationStatus.FAILED}
                    and job.updated_at <= cutoff
                    and (job.slide_spec is not None or job.artifact is not None)
                ):
                    expired.append(job)
            for job in expired:
                self._jobs[job.id] = replace(job, slide_spec=None, artifact=None)
        for job in expired:
            self._audit.record(
                "generation_output_expired",
                job.id,
                None,
                deleted_count=int(job.slide_spec is not None) + int(job.artifact is not None),
            )
        return len(expired)


def _analysis_provider_for_generation(
    environment: Mapping[str, str] = os.environ,
) -> AnalysisProvider:
    try:
        return analysis_provider_from_environment(environment)
    except RuntimeError as error:
        provider = environment.get("MODEL_PROVIDER", "deterministic").strip().lower()
        if provider in {"deepseek", "openai-compatible"} and str(error).startswith(
            "MODEL_DATA_RETENTION_DISABLED"
        ):
            return DeterministicAnalysisProvider()
        raise


@lru_cache(maxsize=1)
def get_generation_service() -> SlideGenerationService:
    provider = _analysis_provider_for_generation()
    return SlideGenerationService(
        get_job_service(),
        FinancialAnalysisService(
            provider,
            fallback_provider=(
                None
                if getattr(provider, "name", None) == "deterministic"
                else DeterministicAnalysisProvider()
            ),
            timeout_seconds=analysis_timeout_seconds_from_environment(),
        ),
        NodePresentationRenderer(),
        policy=get_retention_policy(),
        audit=MetadataAuditLogger(),
    )
