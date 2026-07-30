import asyncio
import json

import httpx2
import pytest

from financial_slides_api.infrastructure.hosted_analysis import (
    DeepSeekAnalysisProvider,
    HostedAnalysisConfig,
    OpenAICompatibleAnalysisProvider,
    analysis_timeout_seconds_from_environment,
    analysis_provider_from_environment,
)
from financial_slides_api.services.analysis import (
    FinancialAnalysisService,
    build_analysis_request,
)
from test_analysis_service import source_document, valid_analysis


def response(output: dict, *, prompt_tokens: int = 100, completion_tokens: int = 50) -> dict:
    return {
        "choices": [{"message": {"content": json.dumps(output)}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


def config(**overrides) -> HostedAnalysisConfig:
    values = {
        "base_url": "https://provider.example/v1",
        "api_key": "test-secret",
        "model": "cheap-model",
        "input_usd_per_million": 1,
        "output_usd_per_million": 2,
    }
    values.update(overrides)
    return HostedAnalysisConfig(**values)


def test_deterministic_is_the_secretless_default() -> None:
    provider = analysis_provider_from_environment({})

    assert provider.name == "deterministic"


def test_deepseek_uses_safe_current_defaults_and_json_mode() -> None:
    requests = []
    output = valid_analysis()

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=response(output))

    provider = analysis_provider_from_environment(
        {"MODEL_PROVIDER": "deepseek", "MODEL_API_KEY": "test-secret"},
        transport=httpx2.MockTransport(handler),
    )
    result = asyncio.run(FinancialAnalysisService(provider).analyze(source_document()))

    sent = json.loads(requests[0].content)
    assert isinstance(provider, DeepSeekAnalysisProvider)
    assert requests[0].url == "https://api.deepseek.com/chat/completions"
    assert sent["model"] == "deepseek-v4-flash"
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["thinking"] == {"type": "disabled"}
    assert "at most 3 executive-summary items" in sent["messages"][0]["content"]
    assert "only permitted source for a metric" in sent["messages"][0]["content"]
    assert "max_tokens" in sent
    assert "max_completion_tokens" not in sent
    assert result.telemetry.provider == "deepseek"


def test_deepseek_defaults_to_an_ipv4_transport() -> None:
    provider = analysis_provider_from_environment(
        {"MODEL_PROVIDER": "deepseek", "MODEL_API_KEY": "test-secret"}
    )

    assert isinstance(provider._transport_for_request(), httpx2.AsyncHTTPTransport)


def test_deepseek_normalizes_half_year_period_to_contract_range() -> None:
    provider = analysis_provider_from_environment(
        {"MODEL_PROVIDER": "deepseek", "MODEL_API_KEY": "test-secret"}
    )
    output = {"metrics": [{"period": {"type": "half-year"}}]}

    assert provider._normalize_output(output)["metrics"][0]["period"]["type"] == "range"


def test_deepseek_drops_invalid_single_operand_calculation() -> None:
    provider = analysis_provider_from_environment(
        {"MODEL_PROVIDER": "deepseek", "MODEL_API_KEY": "test-secret"}
    )
    output = {
        "metrics": [
            {
                "calculation": {
                    "operation": "percentage_change",
                    "operandMetricIds": ["metric-prior"],
                }
            }
        ]
    }

    assert "calculation" not in provider._normalize_output(output)["metrics"][0]


def test_deepseek_canonicalizes_metric_to_exact_source_number() -> None:
    provider = analysis_provider_from_environment(
        {"MODEL_PROVIDER": "deepseek", "MODEL_API_KEY": "test-secret"}
    )
    request = build_analysis_request(source_document())
    output = valid_analysis()
    metric = output["metrics"][0]
    metric["displayedValue"] = "$12.4 million"
    metric["value"] = 12_400_000
    metric["normalizedValue"] = 12_400_000
    metric["unit"] = {"kind": "count", "code": "count", "scaleFactor": 1}
    metric["evidence"][0]["quote"] = "not an exact source quote"

    normalized = provider._normalize_output(output, request)
    metric = normalized["metrics"][0]

    assert metric["value"] == 12.4
    assert metric["normalizedValue"] == 12_400_000
    assert metric["unit"] == {"kind": "currency", "code": "USD", "scaleFactor": 1_000_000}
    assert "quote" not in metric["evidence"][0]


def test_analysis_timeout_uses_environment_configuration() -> None:
    assert analysis_timeout_seconds_from_environment({}) == 30
    assert analysis_timeout_seconds_from_environment({"MODEL_TIMEOUT_SECONDS": "60"}) == 60


def test_hosted_provider_requires_complete_server_configuration() -> None:
    with pytest.raises(RuntimeError, match="MODEL_API_KEY, MODEL_NAME"):
        analysis_provider_from_environment(
            {
                "MODEL_PROVIDER": "openai-compatible",
                "MODEL_BASE_URL": "https://provider.example/v1",
            }
        )


def test_hosted_provider_sends_minimal_context_and_maps_usage() -> None:
    requests = []
    output = valid_analysis()

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=response(output))

    provider = OpenAICompatibleAnalysisProvider(
        config(),
        transport=httpx2.MockTransport(handler),
    )
    result = asyncio.run(FinancialAnalysisService(provider).analyze(source_document()))

    sent = json.loads(requests[0].content)
    user_payload = json.loads(sent["messages"][1]["content"])
    assert requests[0].headers["authorization"] == "Bearer test-secret"
    assert requests[0].url == "https://provider.example/v1/chat/completions"
    assert set(user_payload) == {"documentId", "blocks", "validationFeedback"}
    assert "pages" not in user_payload
    assert sent["response_format"]["json_schema"]["schema"]["title"] == "Analysis v0.2"
    assert result.telemetry.provider == "openai-compatible"
    assert result.telemetry.external_cost_usd == pytest.approx(0.0002)


def test_repair_feedback_is_sent_to_the_second_provider_call() -> None:
    outputs = iter(({"schemaVersion": "0.2"}, valid_analysis()))
    feedback = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent = json.loads(request.content)
        feedback.append(json.loads(sent["messages"][1]["content"])["validationFeedback"])
        return httpx2.Response(200, json=response(next(outputs)))

    provider = OpenAICompatibleAnalysisProvider(
        config(),
        transport=httpx2.MockTransport(handler),
    )
    result = asyncio.run(FinancialAnalysisService(provider).analyze(source_document()))

    assert feedback[0] == []
    assert feedback[1]
    assert result.telemetry.provider_calls == 2
    assert result.telemetry.repair_attempts == 1


@pytest.mark.parametrize(
    "provider_response",
    [
        {"choices": []},
        {"choices": [{"message": {"content": "not-json"}}]},
    ],
)
def test_malformed_provider_response_fails_safely(provider_response: dict) -> None:
    provider = OpenAICompatibleAnalysisProvider(
        config(),
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(200, json=provider_response)
        ),
    )

    with pytest.raises(RuntimeError, match="invalid response"):
        asyncio.run(provider.analyze(build_analysis_request(source_document()), ()))


def test_http_failure_does_not_expose_provider_response() -> None:
    provider = OpenAICompatibleAnalysisProvider(
        config(),
        transport=httpx2.MockTransport(
            lambda request: httpx2.Response(401, text="credential was rejected")
        ),
    )

    with pytest.raises(RuntimeError) as failure:
        asyncio.run(provider.analyze(build_analysis_request(source_document()), ()))

    assert str(failure.value) == "hosted analysis provider returned an invalid response"
    assert "credential" not in str(failure.value)
