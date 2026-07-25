"""Secretless deterministic provider for tests and local development."""

import json
import re
from calendar import monthrange
from collections.abc import Sequence
from datetime import date

from financial_slides_api.domain.analysis import (
    AnalysisRequest,
    ProviderAnalysis,
    ProviderTelemetry,
    SourceNumber,
)


def _identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
    return normalized if normalized[:1].isalpha() else f"id-{normalized or 'value'}"


def _period(label: str | None) -> dict:
    value = label or "2026"
    quarter = re.fullmatch(r"Q([1-4])\s+(\d{4})", value, flags=re.IGNORECASE)
    if quarter:
        quarter_number, year = map(int, quarter.groups())
        start_month = (quarter_number - 1) * 3 + 1
        end_month = start_month + 2
        return {
            "type": "quarter",
            "label": value,
            "startDate": date(year, start_month, 1).isoformat(),
            "endDate": date(year, end_month, monthrange(year, end_month)[1]).isoformat(),
        }
    year_match = re.search(r"\b(20\d{2})\b", value)
    year = int(year_match.group(1)) if year_match else 2026
    return {
        "type": "year",
        "label": value,
        "startDate": date(year, 1, 1).isoformat(),
        "endDate": date(year, 12, 31).isoformat(),
    }


def _unit(number: SourceNumber) -> dict:
    if number.currency:
        return {
            "kind": "currency",
            "code": number.currency,
            "scaleFactor": number.scale_factor or 1,
        }
    if number.unit == "%":
        return {"kind": "percentage", "code": "%", "scaleFactor": 0.01}
    return {"kind": "count", "code": "count", "scaleFactor": 1}


class DeterministicAnalysisProvider:
    """Build one grounded KPI from the first extracted numeric value."""

    name = "deterministic"
    model = "fixture-v1"

    async def analyze(
        self,
        request: AnalysisRequest,
        validation_feedback: Sequence[str],
    ) -> ProviderAnalysis:
        del validation_feedback
        block = next((item for item in request.blocks if item.numbers), None)
        if block is None:
            raise ValueError("deterministic analysis requires one extracted numeric value")
        number = block.numbers[0]
        unit = _unit(number)
        displayed_value = number.displayed_value
        metric_id = _identifier(f"metric-{block.block_id}")
        finding_id = _identifier(f"finding-{block.block_id}")
        evidence = {
            "documentId": request.document_id,
            "pageNumber": block.page_number,
            "blockId": block.block_id,
        }
        output = {
            "schemaVersion": "0.2",
            "analysisId": _identifier(f"analysis-{request.document_id}"),
            "sourceDocumentIds": [request.document_id],
            "executiveSummary": [f"Reported value: {displayed_value}."],
            "metrics": [
                {
                    "id": metric_id,
                    "name": "Reported value",
                    "displayedValue": displayed_value,
                    "value": number.value / unit["scaleFactor"],
                    "normalizedValue": number.value,
                    "unit": unit,
                    "period": _period(number.period),
                    "evidence": [evidence],
                    "confidence": 1,
                }
            ],
            "findings": [
                {
                    "id": finding_id,
                    "kind": "fact",
                    "title": "Reported financial value",
                    "statement": f"The source reports {displayed_value}.",
                    "metricIds": [metric_id],
                    "evidence": [evidence],
                    "confidence": 1,
                }
            ],
            "slideIntents": [
                {
                    "id": _identifier(f"slide-{block.block_id}"),
                    "purpose": "kpi",
                    "title": "Reported financial value",
                    "findingIds": [finding_id],
                    "metricIds": [metric_id],
                    "preferredVisual": "kpi",
                    "priority": 1,
                }
            ],
        }
        input_tokens = sum(len(item.text.split()) for item in request.blocks)
        output_tokens = max(1, len(json.dumps(output)) // 4)
        return ProviderAnalysis(
            output=output,
            telemetry=ProviderTelemetry(
                provider=self.name,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
        )
