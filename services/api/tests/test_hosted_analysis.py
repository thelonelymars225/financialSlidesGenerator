import asyncio
import json

import httpx2
import pytest

from financial_slides_api.infrastructure.hosted_analysis import (
    HostedAnalysisConfig,
    OpenAICompatibleAnalysisProvider,
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
