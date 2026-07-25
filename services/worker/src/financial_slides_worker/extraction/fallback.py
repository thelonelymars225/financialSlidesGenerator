"""Bounded page-level escalation to replaceable document API and VLM providers."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from jsonschema import Draft202012Validator

from financial_slides_worker.extraction.models import (
    CanonicalDocument,
    ExtractionContext,
)

ProviderMethod = Literal["document_api", "vlm"]
FINANCIAL_VALUE = re.compile(
    r"(?<!\w)(?:[-+]\s*)?(?:[$€£]\s*)?\d[\d,]*(?:\.\d+)?\s*(?:%|[kmb]|mn|bn|million|billion)?",
    flags=re.IGNORECASE,
)


class FallbackReason(StrEnum):
    OCR_LOW_CONFIDENCE = "ocr_low_confidence"
    OCR_FAILED = "ocr_failed"
    COMPLEX_VISUAL = "complex_visual"
    AMBIGUOUS_LAYOUT = "ambiguous_layout"


@dataclass(frozen=True)
class PageFallbackCandidate:
    page_number: int
    reason: FallbackReason
    image_png: bytes


@dataclass(frozen=True)
class PageFallbackRequest:
    page_number: int
    reason: FallbackReason
    image_png: bytes
    evidence_page: dict[str, Any]
    response_schema: dict[str, Any]
    max_output_tokens: int
    max_cost_usd: float


@dataclass(frozen=True)
class ProviderPageResult:
    page: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    external_cost_usd: float = 0.0


class PageFallbackProvider(Protocol):
    method: ProviderMethod
    name: str
    model: str
    retains_data: bool

    def extract_page(
        self,
        request: PageFallbackRequest,
        *,
        timeout_seconds: float,
    ) -> ProviderPageResult: ...


class DocumentApiPageProvider(PageFallbackProvider, Protocol):
    method: Literal["document_api"]


class VisionModelPageProvider(PageFallbackProvider, Protocol):
    method: Literal["vlm"]


def _contracts_schema() -> Path:
    return (
        Path(__file__).resolve().parents[5]
        / "packages/contracts/schemas/extracted-document-v0.1.schema.json"
    )


def _warning(code: str, message: str, *, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _page_text(page: dict[str, Any]) -> str:
    values: list[str] = []
    for block in page.get("blocks", ()):
        values.append(str(block.get("text") or block.get("caption") or ""))
        values.extend(str(cell.get("text", "")) for cell in block.get("cells", ()))
    return " ".join(values)


def _financial_values(page: dict[str, Any]) -> set[str]:
    return {
        re.sub(r"\s+", "", match.group(0)).lower()
        for match in FINANCIAL_VALUE.finditer(_page_text(page))
    }


def _has_reliable_evidence(page: dict[str, Any]) -> bool:
    confidences = [
        float(block.get("confidence", 0))
        for block in page.get("blocks", ())
        if "confidence" in block
    ]
    return bool(confidences) and sum(confidences) / len(confidences) >= 0.85


def _page_evidence_is_valid(page: dict[str, Any], page_number: int) -> bool:
    if page.get("pageNumber") != page_number or not page.get("blocks"):
        return False
    for block in page.get("blocks", ()):
        sources = [block.get("source"), *(cell.get("source") for cell in block.get("cells", ()))]
        if any(source and source.get("pageNumber") != page_number for source in sources):
            return False
    return True


def _provider_metadata_is_valid(
    page: dict[str, Any],
    provider: PageFallbackProvider,
) -> bool:
    return all(
        block.get("extraction")
        == {
            "method": provider.method,
            "provider": provider.name,
            "model": provider.model,
        }
        for block in page.get("blocks", ())
    )


class SelectivePageFallback:
    """Escalate explicit candidate pages while retaining safe local evidence."""

    def __init__(
        self,
        providers: Iterable[PageFallbackProvider],
        *,
        schema_path: Path | None = None,
    ) -> None:
        configured = tuple(providers)
        if any(provider.retains_data for provider in configured):
            raise ValueError("fallback providers must disable provider data retention")
        if any(provider.method not in {"document_api", "vlm"} for provider in configured):
            raise ValueError("unsupported fallback provider method")
        self._providers = configured
        schema = json.loads((schema_path or _contracts_schema()).read_text(encoding="utf-8"))
        self._page_schema = {
            "$schema": schema["$schema"],
            "title": "Extracted Document page v0.1",
            "$ref": "#/$defs/page",
            "$defs": schema["$defs"],
        }
        self._validator = Draft202012Validator(schema)

    def _providers_for(self, reason: FallbackReason) -> tuple[PageFallbackProvider, ...]:
        preferred = "vlm" if reason is FallbackReason.COMPLEX_VISUAL else "document_api"
        return tuple(sorted(self._providers, key=lambda provider: provider.method != preferred))

    def _valid_result(
        self,
        document: CanonicalDocument,
        evidence_page: dict[str, Any],
        result_page: dict[str, Any],
        provider: PageFallbackProvider,
    ) -> CanonicalDocument | None:
        page_number = int(evidence_page["pageNumber"])
        if not _page_evidence_is_valid(result_page, page_number) or not _provider_metadata_is_valid(
            result_page, provider
        ):
            return None
        merged = deepcopy(document)
        merged["pages"] = [
            deepcopy(result_page) if page["pageNumber"] == page_number else page
            for page in merged["pages"]
        ]
        return None if next(self._validator.iter_errors(merged), None) else merged

    def apply(
        self,
        document: CanonicalDocument,
        candidates: Iterable[PageFallbackCandidate],
        context: ExtractionContext,
    ) -> CanonicalDocument:
        merged = deepcopy(document)
        warnings = merged.setdefault("warnings", [])
        ordered = tuple(candidates)
        allowed = ordered[: context.limits.max_fallback_pages]
        for candidate in ordered[len(allowed) :]:
            warnings.append(
                _warning(
                    "fallback.page_limit_exceeded",
                    f"Page {candidate.page_number} was not escalated because the page limit was reached.",
                )
            )

        for candidate in allowed:
            context.ensure_time_remaining()
            evidence_page = next(
                page for page in merged["pages"] if page["pageNumber"] == candidate.page_number
            )
            providers = self._providers_for(candidate.reason)
            if not providers:
                warnings.append(
                    _warning(
                        "fallback.unavailable",
                        f"Page {candidate.page_number} needs {candidate.reason.value} fallback but none is configured.",
                    )
                )
                continue

            applied = False
            for provider in providers:
                for _ in range(context.limits.max_provider_attempts):
                    remaining_tokens = (
                        context.limits.max_provider_tokens - context.usage.provider_tokens
                    )
                    remaining_cost = (
                        context.limits.max_external_cost_usd - context.usage.external_cost_usd
                    )
                    if remaining_tokens <= 0 or remaining_cost <= 0:
                        warnings.append(
                            _warning(
                                "fallback.budget_exhausted",
                                f"Page {candidate.page_number} was not escalated because the provider budget was exhausted.",
                            )
                        )
                        break
                    timeout = min(
                        context.seconds_remaining(),
                        context.limits.provider_timeout_seconds,
                    )
                    request = PageFallbackRequest(
                        page_number=candidate.page_number,
                        reason=candidate.reason,
                        image_png=candidate.image_png,
                        evidence_page=deepcopy(evidence_page),
                        response_schema=deepcopy(self._page_schema),
                        max_output_tokens=remaining_tokens,
                        max_cost_usd=remaining_cost,
                    )
                    started = context.clock()
                    try:
                        result = provider.extract_page(request, timeout_seconds=timeout)
                    except TimeoutError:
                        warnings.append(
                            _warning(
                                "fallback.timeout",
                                f"Page {candidate.page_number} provider fallback timed out.",
                            )
                        )
                        continue
                    except Exception:
                        warnings.append(
                            _warning(
                                "fallback.provider_failed",
                                f"Page {candidate.page_number} provider fallback failed safely.",
                            )
                        )
                        continue

                    context.ensure_time_remaining()
                    usage_values = (
                        result.input_tokens,
                        result.output_tokens,
                        result.external_cost_usd,
                    )
                    if (
                        not all(isinstance(value, int) and value >= 0 for value in usage_values[:2])
                        or not isinstance(usage_values[2], int | float)
                        or not math.isfinite(usage_values[2])
                        or usage_values[2] < 0
                    ):
                        warnings.append(
                            _warning(
                                "fallback.invalid_usage",
                                f"Page {candidate.page_number} provider returned invalid usage telemetry.",
                            )
                        )
                        continue
                    tokens = result.input_tokens + result.output_tokens
                    cost = float(result.external_cost_usd)
                    context.usage.provider_tokens += tokens
                    context.usage.external_cost_usd += cost
                    if context.clock() - started > timeout:
                        warnings.append(
                            _warning(
                                "fallback.timeout",
                                f"Page {candidate.page_number} provider fallback exceeded its timeout.",
                            )
                        )
                        continue
                    if tokens > remaining_tokens or cost > remaining_cost:
                        warnings.append(
                            _warning(
                                "fallback.budget_exceeded",
                                f"Page {candidate.page_number} provider output exceeded its token or cost limit.",
                            )
                        )
                        break

                    if (
                        _has_reliable_evidence(evidence_page)
                        and candidate.reason is not FallbackReason.OCR_LOW_CONFIDENCE
                        and not _financial_values(evidence_page).issubset(
                            _financial_values(result.page)
                        )
                    ):
                        warnings.append(
                            _warning(
                                "fallback.financial_value_mismatch",
                                f"Page {candidate.page_number} provider output did not preserve reliable financial evidence.",
                            )
                        )
                        continue

                    validated = self._valid_result(
                        merged,
                        evidence_page,
                        result.page,
                        provider,
                    )
                    if validated is None:
                        warnings.append(
                            _warning(
                                "fallback.invalid_output",
                                f"Page {candidate.page_number} provider output failed contract or evidence checks.",
                            )
                        )
                        continue

                    merged = validated
                    warnings = merged.setdefault("warnings", [])
                    context.usage.provider_pages += 1
                    context.usage.provider_methods.add(provider.method)
                    warnings.append(
                        _warning(
                            f"fallback.applied.{provider.method}",
                            f"Page {candidate.page_number} used bounded {provider.method} fallback for {candidate.reason.value}.",
                            severity="info",
                        )
                    )
                    applied = True
                    break
                if applied:
                    break
        return merged
