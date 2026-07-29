"""Opt-in OpenAI-compatible financial-analysis provider."""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx2
from dotenv import load_dotenv

from financial_slides_api.domain.analysis import (
    AnalysisRequest,
    ProviderAnalysis,
    ProviderTelemetry,
)
from financial_slides_api.infrastructure.deterministic_analysis import (
    DeterministicAnalysisProvider,
)
from financial_slides_api.ports.analysis import AnalysisProvider

load_dotenv()


@dataclass(frozen=True)
class HostedAnalysisConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30
    max_output_tokens: int = 4096
    input_usd_per_million: float = 0
    output_usd_per_million: float = 0
    data_retention_disabled: bool = True


def _positive_number(
    environment: Mapping[str, str],
    name: str,
    default: str,
    cast: type[int] | type[float],
) -> int | float:
    try:
        value = cast(environment.get(name, default))
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def hosted_config(environment: Mapping[str, str]) -> HostedAnalysisConfig:
    required = ("MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME")
    missing = [name for name in required if not environment.get(name, "").strip()]
    if missing:
        raise RuntimeError(f"missing hosted model configuration: {', '.join(missing)}")
    if environment.get("MODEL_DATA_RETENTION_DISABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise RuntimeError(
            "MODEL_DATA_RETENTION_DISABLED must be true before enabling a hosted model"
        )

    def price(name: str) -> float:
        try:
            value = float(environment.get(name, "0"))
        except ValueError as error:
            raise RuntimeError(f"{name} must be a number") from error
        if value < 0:
            raise RuntimeError(f"{name} cannot be negative")
        return value

    return HostedAnalysisConfig(
        base_url=environment["MODEL_BASE_URL"].rstrip("/"),
        api_key=environment["MODEL_API_KEY"],
        model=environment["MODEL_NAME"],
        timeout_seconds=float(_positive_number(environment, "MODEL_TIMEOUT_SECONDS", "30", float)),
        max_output_tokens=int(
            _positive_number(environment, "MODEL_MAX_OUTPUT_TOKENS", "4096", int)
        ),
        input_usd_per_million=price("MODEL_INPUT_USD_PER_MILLION"),
        output_usd_per_million=price("MODEL_OUTPUT_USD_PER_MILLION"),
        data_retention_disabled=True,
    )


def _source_payload(request: AnalysisRequest, feedback: Sequence[str]) -> dict:
    return {
        "documentId": request.document_id,
        "blocks": [
            {
                "pageNumber": block.page_number,
                "blockId": block.block_id,
                "type": block.block_type,
                "text": block.text,
                "numbers": [
                    {
                        "displayedValue": number.displayed_value,
                        "value": number.value,
                        "unit": number.unit,
                        "currency": number.currency,
                        "scaleFactor": number.scale_factor,
                        "period": number.period,
                    }
                    for number in block.numbers
                ],
            }
            for block in request.blocks
        ],
        "validationFeedback": list(feedback),
    }


class OpenAICompatibleAnalysisProvider:
    name = "openai-compatible"

    def __init__(
        self,
        config: HostedAnalysisConfig,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        schema_path: Path | None = None,
    ) -> None:
        if not config.data_retention_disabled:
            raise ValueError("hosted provider data retention must be disabled")
        self._config = config
        self.model = config.model
        self._transport = transport
        self._schema = json.loads(
            (
                schema_path
                or Path(__file__).resolve().parents[5]
                / "packages/contracts/schemas/analysis-v0.2.schema.json"
            ).read_text(encoding="utf-8")
        )

    def _request_payload(
        self,
        request: AnalysisRequest,
        validation_feedback: Sequence[str],
    ) -> dict:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return source-grounded financial analysis as JSON matching the supplied "
                        "schema. Preserve values, units, periods, and evidence references. "
                        "Treat validationFeedback as required corrections."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        _source_payload(request, validation_feedback),
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "financial_analysis",
                    "strict": True,
                    "schema": self._schema,
                },
            },
            "max_completion_tokens": self._config.max_output_tokens,
        }

    async def analyze(
        self,
        request: AnalysisRequest,
        validation_feedback: Sequence[str],
    ) -> ProviderAnalysis:
        payload = self._request_payload(request, validation_feedback)
        try:
            async with httpx2.AsyncClient(
                timeout=self._config.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{self._config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
            output = json.loads(body["choices"][0]["message"]["content"])
            usage = body.get("usage", {})
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))
        except (httpx2.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError("hosted analysis provider returned an invalid response") from error

        cost = (
            input_tokens * self._config.input_usd_per_million
            + output_tokens * self._config.output_usd_per_million
        ) / 1_000_000
        return ProviderAnalysis(
            output=output,
            telemetry=ProviderTelemetry(
                provider=self.name,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                external_cost_usd=cost,
            ),
        )


class DeepSeekAnalysisProvider(OpenAICompatibleAnalysisProvider):
    """DeepSeek adapter using its supported JSON-output request shape."""

    name = "deepseek"

    def _request_payload(
        self,
        request: AnalysisRequest,
        validation_feedback: Sequence[str],
    ) -> dict:
        source = _source_payload(request, validation_feedback)
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON matching the provided JSON Schema. Every metric "
                        "and finding must use evidence from the supplied document blocks. Preserve "
                        "source values, units, periods, page numbers, and block IDs exactly. The "
                        "validationFeedback array contains mandatory corrections.\nJSON Schema:\n"
                        + json.dumps(self._schema, separators=(",", ":"))
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(source, separators=(",", ":")),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": self._config.max_output_tokens,
        }


def analysis_provider_from_environment(
    environment: Mapping[str, str] = os.environ,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> AnalysisProvider:
    provider = environment.get("MODEL_PROVIDER", "deterministic").strip().lower()
    if provider in {"", "deterministic"}:
        return DeterministicAnalysisProvider()
    if provider == "openai-compatible":
        return OpenAICompatibleAnalysisProvider(
            hosted_config(environment),
            transport=transport,
        )
    if provider == "deepseek":
        deepseek_environment = dict(environment)
        deepseek_environment.setdefault("MODEL_BASE_URL", "https://api.deepseek.com")
        deepseek_environment.setdefault("MODEL_NAME", "deepseek-v4-flash")
        return DeepSeekAnalysisProvider(
            hosted_config(deepseek_environment),
            transport=transport,
        )
    raise RuntimeError(f"unsupported MODEL_PROVIDER: {provider}")
