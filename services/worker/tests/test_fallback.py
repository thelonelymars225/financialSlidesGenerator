from __future__ import annotations

from copy import deepcopy
from time import perf_counter

import pytest

from financial_slides_worker.extraction import (
    ExtractionLimits,
    FallbackReason,
    PageFallbackCandidate,
    ProviderPageResult,
    SelectivePageFallback,
)
from financial_slides_worker.extraction.models import ExtractionContext


def page(page_number: int, text: str = "Revenue was $12.4m") -> dict:
    return {
        "pageNumber": page_number,
        "width": 612,
        "height": 792,
        "coordinateUnit": "pt",
        "blocks": [
            {
                "id": f"page-{page_number}-text-1",
                "type": "text",
                "order": 0,
                "text": text,
                "source": {
                    "sourceId": "source-fixture",
                    "pageNumber": page_number,
                    "sectionPath": [f"Page {page_number}"],
                },
                "confidence": 0.95,
                "extraction": {"method": "native_pdf", "provider": "fixture"},
                "warnings": [],
            }
        ],
    }


def document() -> dict:
    return {
        "schemaVersion": "0.1",
        "documentId": "document-fixture",
        "source": {
            "sourceId": "source-fixture",
            "inputType": "file",
            "mediaType": "application/pdf",
            "fileName": "fixture.pdf",
            "contentHash": f"sha256:{'a' * 64}",
        },
        "pages": [page(1), page(2, "Chart revenue was $12.4m")],
        "warnings": [],
    }


def provider_page(request, provider) -> dict:
    result = deepcopy(request.evidence_page)
    for block in result["blocks"]:
        block["extraction"] = {
            "method": provider.method,
            "provider": provider.name,
            "model": provider.model,
        }
    return result


class FakeProvider:
    retains_data = False

    def __init__(self, method: str, *outputs) -> None:
        self.method = method
        self.name = f"fixture-{method}"
        self.model = "fixture-v1"
        self.outputs = iter(outputs)
        self.requests = []
        self.timeouts = []

    def extract_page(self, request, *, timeout_seconds):
        self.requests.append(request)
        self.timeouts.append(timeout_seconds)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        if callable(output):
            output = output(request, self)
        return output


def result(request, provider, *, tokens: int = 20, cost: float = 0.01):
    return ProviderPageResult(
        provider_page(request, provider),
        input_tokens=tokens // 2,
        output_tokens=tokens - tokens // 2,
        external_cost_usd=cost,
    )


def context(limits: ExtractionLimits | None = None) -> ExtractionContext:
    clock = perf_counter
    return ExtractionContext(limits or ExtractionLimits(), clock() + 30, clock)


def test_only_selected_page_is_sent_and_vlm_is_preferred_for_visuals() -> None:
    document_api = FakeProvider("document_api", AssertionError("should not run"))
    vlm = FakeProvider("vlm", result)
    extraction_context = context()

    observed = SelectivePageFallback((document_api, vlm)).apply(
        document(),
        (PageFallbackCandidate(2, FallbackReason.COMPLEX_VISUAL, b"page-2-png"),),
        extraction_context,
    )

    assert document_api.requests == []
    assert len(vlm.requests) == 1
    assert vlm.requests[0].page_number == 2
    assert vlm.requests[0].image_png == b"page-2-png"
    assert vlm.requests[0].evidence_page["pageNumber"] == 2
    assert vlm.requests[0].response_schema["title"] == "Extracted Document page v0.1"
    assert observed["pages"][0] == document()["pages"][0]
    assert observed["pages"][1]["blocks"][0]["extraction"]["method"] == "vlm"
    assert extraction_context.usage.provider_pages == 1
    assert extraction_context.usage.provider_tokens == 20
    assert extraction_context.usage.external_cost_usd == 0.01


def test_document_api_retries_before_vlm_for_ocr_failures() -> None:
    document_api = FakeProvider("document_api", TimeoutError(), result)
    vlm = FakeProvider("vlm", AssertionError("should not run"))

    observed = SelectivePageFallback((vlm, document_api)).apply(
        document(),
        (PageFallbackCandidate(1, FallbackReason.OCR_FAILED, b"page-1-png"),),
        context(),
    )

    assert len(document_api.requests) == 2
    assert vlm.requests == []
    assert observed["pages"][0]["blocks"][0]["extraction"]["method"] == "document_api"
    assert any(warning["code"] == "fallback.timeout" for warning in observed["warnings"])


def test_invalid_evidence_and_financial_mismatch_preserve_local_page() -> None:
    def invalid(request, provider):
        response = provider_page(request, provider)
        response["blocks"][0]["text"] = "Revenue was $9.9m"
        return ProviderPageResult(response)

    provider = FakeProvider("vlm", invalid, invalid)
    original = document()
    observed = SelectivePageFallback((provider,)).apply(
        original,
        (PageFallbackCandidate(2, FallbackReason.COMPLEX_VISUAL, b"page-2-png"),),
        context(),
    )

    assert observed["pages"][1] == original["pages"][1]
    assert len(provider.requests) == 2
    assert any(
        warning["code"] == "fallback.financial_value_mismatch" for warning in observed["warnings"]
    )


def test_wrong_page_evidence_and_invalid_usage_are_rejected() -> None:
    def wrong_page(request, provider):
        response = provider_page(request, provider)
        response["pageNumber"] = 99
        return ProviderPageResult(response)

    provider = FakeProvider(
        "document_api",
        wrong_page,
        ProviderPageResult(page(1), input_tokens=-1, external_cost_usd=float("nan")),
    )
    observed = SelectivePageFallback((provider,)).apply(
        document(),
        (PageFallbackCandidate(1, FallbackReason.OCR_FAILED, b"page-1-png"),),
        context(),
    )

    assert observed["pages"][0] == document()["pages"][0]
    assert any(warning["code"] == "fallback.invalid_output" for warning in observed["warnings"])
    assert any(warning["code"] == "fallback.invalid_usage" for warning in observed["warnings"])


def test_page_token_and_cost_limits_stop_unbounded_escalation() -> None:
    provider = FakeProvider(
        "document_api",
        lambda request, configured: result(request, configured, tokens=20, cost=0.2),
    )
    extraction_context = context(
        ExtractionLimits(
            max_fallback_pages=1,
            max_provider_attempts=1,
            max_provider_tokens=10,
            max_external_cost_usd=0.1,
        )
    )

    observed = SelectivePageFallback((provider,)).apply(
        document(),
        (
            PageFallbackCandidate(1, FallbackReason.OCR_FAILED, b"page-1-png"),
            PageFallbackCandidate(2, FallbackReason.OCR_FAILED, b"page-2-png"),
        ),
        extraction_context,
    )

    assert len(provider.requests) == 1
    assert provider.requests[0].max_output_tokens == 10
    assert provider.requests[0].max_cost_usd == 0.1
    assert any(warning["code"] == "fallback.budget_exceeded" for warning in observed["warnings"])
    assert any(
        warning["code"] == "fallback.page_limit_exceeded" for warning in observed["warnings"]
    )


def test_provider_retention_must_be_disabled() -> None:
    provider = FakeProvider("vlm", result)
    provider.retains_data = True

    with pytest.raises(ValueError, match="retention"):
        SelectivePageFallback((provider,))
