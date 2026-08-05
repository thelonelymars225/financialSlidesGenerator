import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

from financial_slides_api.domain.analysis import (
    AnalysisError,
    AnalysisFailureCode,
    ProviderAnalysis,
    ProviderTelemetry,
)
from financial_slides_api.infrastructure.deterministic_analysis import (
    DeterministicAnalysisProvider,
)
from financial_slides_api.services.analysis import FinancialAnalysisService
from financial_slides_api.services.analysis import build_analysis_request

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "packages" / "contracts" / "examples" / "extracted-document-text-v0.1.json"
FINANCIAL_EXAMPLE = (
    ROOT / "packages" / "contracts" / "examples" / "extracted-document-financial-v0.2.json"
)


def source_document() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def valid_analysis() -> dict:
    return asyncio.run(
        FinancialAnalysisService(DeterministicAnalysisProvider()).analyze(source_document())
    ).analysis


class ScriptedProvider:
    def __init__(self, *outputs: dict, delay: float = 0) -> None:
        self.outputs = outputs
        self.delay = delay
        self.calls = 0
        self.feedback: list[tuple[str, ...]] = []

    async def analyze(self, request, validation_feedback) -> ProviderAnalysis:
        del request
        self.feedback.append(tuple(validation_feedback))
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        output = self.outputs[min(self.calls - 1, len(self.outputs) - 1)]
        return ProviderAnalysis(
            output=output,
            telemetry=ProviderTelemetry(
                provider="scripted",
                model="test",
                input_tokens=10,
                output_tokens=20,
                external_cost_usd=0.001,
            ),
        )


class FailingProvider:
    async def analyze(self, request, validation_feedback) -> ProviderAnalysis:
        del request, validation_feedback
        raise RuntimeError("sensitive provider detail")


def run_analysis(service: FinancialAnalysisService, document: dict | None = None, **kwargs):
    return asyncio.run(service.analyze(document or source_document(), **kwargs))


def test_deterministic_provider_returns_grounded_valid_analysis() -> None:
    result = run_analysis(
        FinancialAnalysisService(DeterministicAnalysisProvider()),
    )

    metric = result.analysis["metrics"][0]
    assert metric["normalizedValue"] == 12_400_000
    assert metric["unit"] == {"kind": "currency", "code": "USD", "scaleFactor": 1_000_000}
    assert metric["period"]["label"] == "Q2 2026"
    assert metric["evidence"][0]["blockId"] == "text-1"
    assert result.telemetry.provider_calls == 1
    assert result.telemetry.repair_attempts == 0
    assert result.telemetry.external_cost_usd == 0


def test_analysis_boundary_accepts_finance_aware_extraction_v02() -> None:
    document = json.loads(FINANCIAL_EXAMPLE.read_text(encoding="utf-8"))

    result = run_analysis(FinancialAnalysisService(DeterministicAnalysisProvider()), document)

    assert result.analysis["sourceDocumentIds"] == ["document-financial-001"]
    assert result.analysis["metrics"][0]["normalizedValue"] == 0.18


def test_plain_extracted_text_gets_a_bounded_numeric_fallback() -> None:
    document = source_document()
    block = document["pages"][0]["blocks"][0]
    block.pop("numericValues")

    result = run_analysis(
        FinancialAnalysisService(DeterministicAnalysisProvider()),
        document,
    )

    metric = result.analysis["metrics"][0]
    assert metric["displayedValue"] == "$12.4 million"
    assert metric["normalizedValue"] == 12_400_000
    assert metric["period"]["label"] == "Q2 2026"


def test_plain_text_preserves_multiple_period_specific_values() -> None:
    document = source_document()
    block = document["pages"][0]["blocks"][0]
    block.pop("numericValues")
    block["text"] = "Q1 2026 | $10.0m\nQ2 2026 | $12.4m"

    request = build_analysis_request(document)

    assert [(number.value, number.period) for number in request.blocks[0].numbers] == [
        (10_000_000, "Q1 2026"),
        (12_400_000, "Q2 2026"),
    ]


@pytest.mark.parametrize(
    ("density", "max_bullets"),
    [
        ("concise", 3),
        ("balanced", 5),
        ("detailed", 7),
    ],
)
def test_analysis_request_resolves_density_constraints(
    density: str,
    max_bullets: int,
) -> None:
    request = build_analysis_request(source_document(), density, slide_count=10)

    assert request.density_profile.value == density
    assert request.requested_slide_count == 10
    assert request.density_constraints is not None
    assert request.density_constraints.max_bullets_per_slide == max_bullets


def test_plain_table_numbers_are_available_for_grounded_analysis() -> None:
    document = source_document()
    block = document["pages"][0]["blocks"][0]
    block.pop("numericValues")
    block["text"] = "Adjusted net income 4,007; prior period (4,582); gearing 12.5%"

    numbers = build_analysis_request(document).blocks[0].numbers

    assert any(number.displayed_value == "4,007" and number.value == 4007 for number in numbers)
    assert any(number.displayed_value == "(4,582)" and number.value == -4582 for number in numbers)
    assert any(number.displayed_value == "12.5%" and number.value == 0.125 for number in numbers)


def test_invalid_output_receives_one_targeted_repair() -> None:
    provider = ScriptedProvider({"schemaVersion": "0.2"}, valid_analysis())

    result = run_analysis(FinancialAnalysisService(provider))

    assert provider.calls == 2
    assert provider.feedback[0] == ()
    assert provider.feedback[1]
    assert result.telemetry.repair_attempts == 1
    assert result.telemetry.input_tokens == 20
    assert result.telemetry.external_cost_usd == pytest.approx(0.002)


def test_repair_exhaustion_is_a_typed_failure() -> None:
    provider = ScriptedProvider({"schemaVersion": "0.2"})

    with pytest.raises(AnalysisError) as failure:
        run_analysis(FinancialAnalysisService(provider))

    assert failure.value.code is AnalysisFailureCode.INVALID_OUTPUT
    assert failure.value.retryable is False
    assert provider.calls == 2


def test_repair_exhaustion_uses_validated_grounded_fallback() -> None:
    provider = ScriptedProvider({"schemaVersion": "0.2"})
    service = FinancialAnalysisService(
        provider,
        fallback_provider=DeterministicAnalysisProvider(),
    )

    result = run_analysis(service)

    assert provider.calls == 2
    assert result.telemetry.provider == "deterministic"
    assert result.telemetry.provider_calls == 3
    assert result.telemetry.fallback_used is True
    assert result.telemetry.repair_attempts == 1
    assert result.analysis["metrics"][0]["displayedValue"] == "$12.4 million"


def test_timeout_is_typed_and_retryable() -> None:
    provider = ScriptedProvider(valid_analysis(), delay=0.05)

    with pytest.raises(AnalysisError) as failure:
        run_analysis(FinancialAnalysisService(provider, timeout_seconds=0.001))

    assert failure.value.code is AnalysisFailureCode.TIMEOUT
    assert failure.value.retryable is True


def test_provider_failure_is_typed_without_exposing_provider_detail() -> None:
    with pytest.raises(AnalysisError) as failure:
        run_analysis(FinancialAnalysisService(FailingProvider()))

    assert failure.value.code is AnalysisFailureCode.PROVIDER_FAILURE
    assert failure.value.message == "analysis provider failed"
    assert failure.value.retryable is True


def test_cancellation_stops_before_provider_content_is_sent() -> None:
    provider = ScriptedProvider(valid_analysis())

    with pytest.raises(AnalysisError) as failure:
        run_analysis(
            FinancialAnalysisService(provider),
            is_cancelled=lambda: True,
        )

    assert failure.value.code is AnalysisFailureCode.CANCELLED
    assert provider.calls == 0


def test_missing_evidence_block_is_an_ungrounded_failure() -> None:
    analysis = valid_analysis()
    analysis["metrics"][0]["evidence"][0]["blockId"] = "missing-block"
    provider = ScriptedProvider(analysis)

    with pytest.raises(AnalysisError) as failure:
        run_analysis(FinancialAnalysisService(provider, max_repair_attempts=0))

    assert failure.value.code is AnalysisFailureCode.UNGROUNDED_OUTPUT


def test_changed_numeric_value_is_an_ungrounded_failure() -> None:
    analysis = deepcopy(valid_analysis())
    analysis["metrics"][0]["normalizedValue"] = 9_999
    provider = ScriptedProvider(analysis)

    with pytest.raises(AnalysisError) as failure:
        run_analysis(FinancialAnalysisService(provider, max_repair_attempts=0))

    assert failure.value.code is AnalysisFailureCode.UNGROUNDED_OUTPUT


def test_invalid_source_is_rejected_before_provider_call() -> None:
    document = source_document()
    document["schemaVersion"] = "9.9"
    provider = ScriptedProvider(valid_analysis())

    with pytest.raises(AnalysisError) as failure:
        run_analysis(FinancialAnalysisService(provider), document)

    assert failure.value.code is AnalysisFailureCode.INVALID_SOURCE
    assert provider.calls == 0
