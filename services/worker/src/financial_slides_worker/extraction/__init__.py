"""Provider-neutral native document extraction."""

from financial_slides_worker.extraction.errors import (
    CorruptFileError,
    EmptyInputError,
    EncryptedFileError,
    ExtractionError,
    ExtractionLimitError,
    ExtractionTimeoutError,
    MediaTypeMismatchError,
    OcrFailedError,
    UnsupportedFileError,
)
from financial_slides_worker.extraction.fallback import (
    DocumentApiPageProvider,
    FallbackReason,
    PageFallbackCandidate,
    PageFallbackProvider,
    PageFallbackRequest,
    ProviderPageResult,
    SelectivePageFallback,
    VisionModelPageProvider,
)
from financial_slides_worker.extraction.models import (
    ExtractionLimits,
    ExtractionResult,
    ExtractionTelemetry,
    FileSource,
    TextSource,
)
from financial_slides_worker.extraction.service import ExtractionService

__all__ = [
    "CorruptFileError",
    "DocumentApiPageProvider",
    "EmptyInputError",
    "EncryptedFileError",
    "ExtractionError",
    "ExtractionLimitError",
    "ExtractionLimits",
    "ExtractionResult",
    "ExtractionService",
    "ExtractionTelemetry",
    "ExtractionTimeoutError",
    "FallbackReason",
    "FileSource",
    "MediaTypeMismatchError",
    "OcrFailedError",
    "PageFallbackCandidate",
    "PageFallbackProvider",
    "PageFallbackRequest",
    "ProviderPageResult",
    "SelectivePageFallback",
    "TextSource",
    "UnsupportedFileError",
    "VisionModelPageProvider",
]
