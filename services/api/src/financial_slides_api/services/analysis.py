"""Bounded, provider-independent financial-analysis orchestration."""

import asyncio
import math
import os
from collections.abc import Callable, Iterable, Sequence
from json import loads
from pathlib import Path
from time import perf_counter
from typing import Any

from jsonschema import Draft202012Validator

from financial_slides_api.domain.analysis import (
    AnalysisError,
    AnalysisFailureCode,
    AnalysisRequest,
    AnalysisResult,
    AnalysisSourceBlock,
    AnalysisTelemetry,
    ProviderTelemetry,
    SourceNumber,
)
from financial_slides_api.ports.analysis import AnalysisProvider

MAX_FEEDBACK_ERRORS = 20


def _default_contracts_dir() -> Path:
    configured = os.getenv("FINANCIAL_SLIDES_CONTRACTS_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[5] / "packages" / "contracts" / "schemas"


def _validator(schema_path: Path) -> Draft202012Validator:
    try:
        schema = loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"unable to load contract schema: {schema_path.name}") from error
    return Draft202012Validator(schema)


def _numeric_values(block: dict[str, Any]) -> tuple[SourceNumber, ...]:
    values: Iterable[dict[str, Any]]
    if block["type"] == "table":
        values = (cell["numericValue"] for cell in block.get("cells", ()) if "numericValue" in cell)
    else:
        values = block.get("numericValues", ())
    return tuple(
        SourceNumber(
            displayed_value=value["displayedValue"],
            value=float(value["value"]),
            unit=value.get("unit"),
            currency=value.get("currency"),
            scale_factor=value.get("scaleFactor"),
            period=value.get("period"),
        )
        for value in values
    )


def _block_text(block: dict[str, Any]) -> str:
    if block["type"] == "text":
        return block["text"]
    if block["type"] == "table":
        ordered = sorted(block.get("cells", ()), key=lambda cell: (cell["row"], cell["column"]))
        return " | ".join(cell["text"] for cell in ordered if cell["text"])
    return block.get("altText", "")


def build_analysis_request(document: dict[str, Any]) -> AnalysisRequest:
    """Keep only evidence-bearing content needed by a model provider."""

    blocks = tuple(
        AnalysisSourceBlock(
            page_number=page["pageNumber"],
            block_id=block["id"],
            block_type=block["type"],
            text=_block_text(block),
            numbers=_numeric_values(block),
        )
        for page in document["pages"]
        for block in sorted(page["blocks"], key=lambda item: item["order"])
    )
    return AnalysisRequest(document_id=document["documentId"], blocks=blocks)


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _metric_matches_source(metric: dict[str, Any], number: SourceNumber) -> bool:
    unit = metric["unit"]
    normalized_value = float(metric["normalizedValue"])
    if not _close(normalized_value, number.value):
        return False
    if number.currency and unit["code"] != number.currency:
        return False
    if number.unit and number.unit not in {unit["code"], unit["kind"]}:
        return False
    if number.period and metric["period"]["label"] != number.period:
        return False
    return _close(float(metric["value"]) * float(unit["scaleFactor"]), normalized_value)


def grounding_errors(
    analysis: dict[str, Any],
    request: AnalysisRequest,
) -> tuple[str, ...]:
    """Validate cross-references, evidence locations, and direct numeric fidelity."""

    errors: list[str] = []
    blocks = {(block.page_number, block.block_id): block for block in request.blocks}
    metric_ids = {metric["id"] for metric in analysis.get("metrics", ())}
    finding_ids = {finding["id"] for finding in analysis.get("findings", ())}

    if analysis.get("sourceDocumentIds") != [request.document_id]:
        errors.append("sourceDocumentIds must contain only the analyzed document")

    def validate_evidence(owner: str, evidence_items: Sequence[dict[str, Any]]) -> None:
        for evidence in evidence_items:
            if evidence.get("documentId") != request.document_id:
                errors.append(f"{owner} references another document")
                continue
            block = blocks.get((evidence.get("pageNumber"), evidence.get("blockId")))
            if block is None:
                errors.append(f"{owner} references a missing source block")
                continue
            quote = evidence.get("quote")
            if quote and " ".join(quote.split()) not in " ".join(block.text.split()):
                errors.append(f"{owner} quote is not present in its source block")

    for metric in analysis.get("metrics", ()):
        owner = f"metric {metric.get('id', '<unknown>')}"
        validate_evidence(owner, metric.get("evidence", ()))
        calculation = metric.get("calculation")
        if calculation:
            missing = set(calculation["operandMetricIds"]) - metric_ids
            if missing:
                errors.append(f"{owner} has missing calculation operands")
            continue
        source_numbers = tuple(
            number
            for evidence in metric.get("evidence", ())
            if evidence.get("documentId") == request.document_id
            for block in (blocks.get((evidence.get("pageNumber"), evidence.get("blockId"))),)
            if block
            for number in block.numbers
        )
        if not any(_metric_matches_source(metric, number) for number in source_numbers):
            errors.append(f"{owner} does not preserve a source numeric value, unit, and period")

    for finding in analysis.get("findings", ()):
        owner = f"finding {finding.get('id', '<unknown>')}"
        validate_evidence(owner, finding.get("evidence", ()))
        if set(finding.get("metricIds", ())) - metric_ids:
            errors.append(f"{owner} references a missing metric")

    for slide in analysis.get("slideIntents", ()):
        owner = f"slide intent {slide.get('id', '<unknown>')}"
        if set(slide.get("metricIds", ())) - metric_ids:
            errors.append(f"{owner} references a missing metric")
        if set(slide.get("findingIds", ())) - finding_ids:
            errors.append(f"{owner} references a missing finding")
    return tuple(errors)


def _schema_errors(
    validator: Draft202012Validator,
    value: dict[str, Any],
) -> tuple[str, ...]:
    return tuple(
        f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(
            validator.iter_errors(value),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    )


class FinancialAnalysisService:
    def __init__(
        self,
        provider: AnalysisProvider,
        *,
        contracts_dir: Path | None = None,
        timeout_seconds: float = 30,
        max_repair_attempts: int = 1,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        if max_repair_attempts not in {0, 1}:
            raise ValueError("max_repair_attempts must be zero or one")
        schemas = contracts_dir or _default_contracts_dir()
        self._source_validator = _validator(schemas / "extracted-document-v0.1.schema.json")
        self._analysis_validator = _validator(schemas / "analysis-v0.2.schema.json")
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._max_repair_attempts = max_repair_attempts
        self._timer = timer

    async def analyze(
        self,
        document: dict[str, Any],
        *,
        is_cancelled: Callable[[], bool] = lambda: False,
    ) -> AnalysisResult:
        source_errors = _schema_errors(self._source_validator, document)
        if source_errors:
            raise AnalysisError(
                AnalysisFailureCode.INVALID_SOURCE,
                "source document does not satisfy extracted-document-v0.1",
            )

        request = build_analysis_request(document)
        feedback: tuple[str, ...] = ()
        totals = ProviderTelemetry(provider="unknown", model="unknown")
        started = self._timer()

        for provider_call in range(1, self._max_repair_attempts + 2):
            if is_cancelled():
                raise AnalysisError(AnalysisFailureCode.CANCELLED, "analysis was cancelled")
            try:
                response = await asyncio.wait_for(
                    self._provider.analyze(request, feedback),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as error:
                raise AnalysisError(
                    AnalysisFailureCode.TIMEOUT,
                    "analysis provider timed out",
                    retryable=True,
                ) from error
            except asyncio.CancelledError:
                raise
            except AnalysisError:
                raise
            except Exception as error:
                raise AnalysisError(
                    AnalysisFailureCode.PROVIDER_FAILURE,
                    "analysis provider failed",
                    retryable=True,
                ) from error
            if is_cancelled():
                raise AnalysisError(AnalysisFailureCode.CANCELLED, "analysis was cancelled")

            totals = ProviderTelemetry(
                provider=response.telemetry.provider,
                model=response.telemetry.model,
                input_tokens=totals.input_tokens + response.telemetry.input_tokens,
                output_tokens=totals.output_tokens + response.telemetry.output_tokens,
                external_cost_usd=(totals.external_cost_usd + response.telemetry.external_cost_usd),
            )
            schema_errors = _schema_errors(self._analysis_validator, response.output)
            evidence_errors = () if schema_errors else grounding_errors(response.output, request)
            validation_errors = schema_errors + evidence_errors
            if not validation_errors:
                return AnalysisResult(
                    analysis=response.output,
                    telemetry=AnalysisTelemetry(
                        provider=totals.provider,
                        model=totals.model,
                        duration_ms=(self._timer() - started) * 1000,
                        provider_calls=provider_call,
                        repair_attempts=provider_call - 1,
                        input_tokens=totals.input_tokens,
                        output_tokens=totals.output_tokens,
                        external_cost_usd=totals.external_cost_usd,
                    ),
                )
            feedback = validation_errors[:MAX_FEEDBACK_ERRORS]

        failure_code = (
            AnalysisFailureCode.INVALID_OUTPUT
            if schema_errors
            else AnalysisFailureCode.UNGROUNDED_OUTPUT
        )
        raise AnalysisError(
            failure_code,
            "analysis output remained invalid after bounded repair",
        )
