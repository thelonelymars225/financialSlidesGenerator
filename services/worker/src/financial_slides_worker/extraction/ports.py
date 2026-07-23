"""Replaceable parser boundary for native file formats."""

from typing import Protocol

from financial_slides_worker.extraction.models import (
    CanonicalDocument,
    ExtractionContext,
    FileSource,
)


class FileExtractor(Protocol):
    media_type: str
    route: str

    def extract(
        self,
        source: FileSource,
        context: ExtractionContext,
    ) -> CanonicalDocument: ...
