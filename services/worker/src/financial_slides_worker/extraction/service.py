"""Extraction orchestration with replaceable parsers and bounded local routes."""

from collections.abc import Callable, Iterable
from time import perf_counter

from financial_slides_worker.extraction.errors import (
    EmptyInputError,
    ExtractionLimitError,
    UnsupportedFileError,
)
from financial_slides_worker.extraction.models import (
    ExtractionContext,
    ExtractionLimits,
    ExtractionResult,
    ExtractionTelemetry,
    FileSource,
    TextSource,
)
from financial_slides_worker.extraction.native import PdfPlumberExtractor, extract_pasted_text
from financial_slides_worker.extraction.ports import FileExtractor
from financial_slides_worker.extraction.routing import validate_file_source


class ExtractionService:
    """Select a deterministic local route and emit the canonical contract."""

    def __init__(
        self,
        extractors: Iterable[FileExtractor] | None = None,
        limits: ExtractionLimits | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        configured = tuple(extractors) if extractors is not None else (PdfPlumberExtractor(),)
        self._extractors = {extractor.media_type: extractor for extractor in configured}
        self._limits = limits or ExtractionLimits()
        self._clock = clock

    def extract_text(self, source: TextSource) -> ExtractionResult:
        encoded = source.text.encode("utf-8")
        if not source.text.strip():
            raise EmptyInputError()
        if len(encoded) > self._limits.max_text_bytes:
            raise ExtractionLimitError(
                "text_too_large",
                f"The pasted text exceeds the {self._limits.max_text_bytes}-byte limit.",
            )

        started = self._clock()
        document = extract_pasted_text(source.text)
        return ExtractionResult(
            document=document,
            telemetry=ExtractionTelemetry(
                route="pasted_text",
                duration_ms=max(0.0, (self._clock() - started) * 1000),
            ),
        )

    def extract_file(self, source: FileSource) -> ExtractionResult:
        media_type = validate_file_source(source, self._limits)
        extractor = self._extractors.get(media_type)
        if extractor is None:
            raise UnsupportedFileError(f"No local parser is registered for {media_type!r}.")

        started = self._clock()
        context = ExtractionContext(
            limits=self._limits,
            deadline=started + self._limits.timeout_seconds,
            clock=self._clock,
        )
        document = extractor.extract(source, context)
        context.ensure_time_remaining()
        return ExtractionResult(
            document=document,
            telemetry=ExtractionTelemetry(
                route=extractor.route,
                duration_ms=max(0.0, (self._clock() - started) * 1000),
            ),
        )
