"""API-facing service boundary for deterministic native extraction."""

from financial_slides_worker import (
    ExtractionResult,
    ExtractionService,
    FileSource,
    TextSource,
)


class NativeExtractionService:
    """Expose worker extraction without putting parser logic in controllers."""

    def __init__(self, worker_service: ExtractionService | None = None) -> None:
        self._worker_service = worker_service or ExtractionService()

    def extract_text(self, source_text: str) -> ExtractionResult:
        return self._worker_service.extract_text(TextSource(text=source_text))

    def extract_file(
        self,
        data: bytes,
        file_name: str,
        declared_media_type: str | None = None,
    ) -> ExtractionResult:
        return self._worker_service.extract_file(
            FileSource(
                data=data,
                file_name=file_name,
                declared_media_type=declared_media_type,
            )
        )
