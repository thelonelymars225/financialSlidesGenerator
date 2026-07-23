"""Immutable inputs, limits, results, and extraction telemetry."""

from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ExtractionContext:
    limits: ExtractionLimits
    deadline: float
    clock: Callable[[], float]

    def ensure_time_remaining(self) -> None:
        if self.clock() > self.deadline:
            raise ExtractionTimeoutError()
