"""Immutable financial-analysis models and typed failures."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AnalysisFailureCode(StrEnum):
    INVALID_SOURCE = "invalid_source"
    PROVIDER_FAILURE = "provider_failure"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    INVALID_OUTPUT = "invalid_output"
    UNGROUNDED_OUTPUT = "ungrounded_output"


class AnalysisError(Exception):
    """A safe failure that controllers and workers can expose without provider details."""

    def __init__(
        self,
        code: AnalysisFailureCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class SourceNumber:
    displayed_value: str
    value: float
    unit: str | None
    currency: str | None
    scale_factor: float | None
    period: str | None


@dataclass(frozen=True)
class AnalysisSourceBlock:
    page_number: int
    block_id: str
    block_type: str
    text: str
    numbers: tuple[SourceNumber, ...]


@dataclass(frozen=True)
class AnalysisRequest:
    document_id: str
    blocks: tuple[AnalysisSourceBlock, ...]


@dataclass(frozen=True)
class ProviderTelemetry:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    external_cost_usd: float = 0


@dataclass(frozen=True)
class ProviderAnalysis:
    output: dict[str, Any]
    telemetry: ProviderTelemetry


@dataclass(frozen=True)
class AnalysisTelemetry:
    provider: str
    model: str
    duration_ms: float
    provider_calls: int
    repair_attempts: int
    input_tokens: int
    output_tokens: int
    external_cost_usd: float


@dataclass(frozen=True)
class AnalysisResult:
    analysis: dict[str, Any]
    telemetry: AnalysisTelemetry
