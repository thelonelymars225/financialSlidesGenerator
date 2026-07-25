"""Immutable inputs, limits, results, and extraction telemetry."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from financial_slides_worker.extraction.errors import ExtractionTimeoutError

CanonicalDocument = dict[str, Any]


@dataclass(frozen=True)
class TextSource:
    text: str


@dataclass(frozen=True)
class FileSource:
    data: bytes
    file_name: str
    declared_media_type: str | None = None


@dataclass(frozen=True)
class ExtractionLimits:
    max_file_bytes: int = 25 * 1024 * 1024
    max_text_bytes: int = 2 * 1024 * 1024
    max_pages: int = 200
    max_ocr_pages: int = 20
    max_fallback_pages: int = 5
    max_provider_attempts: int = 2
    max_provider_tokens: int = 12_000
    max_external_cost_usd: float = 0.25
    provider_timeout_seconds: float = 10.0
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ExtractionTelemetry:
    route: str
    duration_ms: float
    external_cost_usd: float = 0.0


@dataclass(frozen=True)
class ExtractionResult:
    document: CanonicalDocument
    telemetry: ExtractionTelemetry


@dataclass
class ExtractionUsage:
    provider_pages: int = 0
    provider_tokens: int = 0
    external_cost_usd: float = 0.0
    provider_methods: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ExtractionContext:
    limits: ExtractionLimits
    deadline: float
    clock: Callable[[], float]
    usage: ExtractionUsage = field(default_factory=ExtractionUsage, compare=False)

    def ensure_time_remaining(self) -> None:
        if self.clock() > self.deadline:
            raise ExtractionTimeoutError()

    def seconds_remaining(self) -> float:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise ExtractionTimeoutError()
        return remaining
