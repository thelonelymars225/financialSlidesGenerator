"""Pure file-signature routing and input-limit checks."""

from financial_slides_worker.extraction.errors import (
    EmptyInputError,
    ExtractionLimitError,
    MediaTypeMismatchError,
    UnsupportedFileError,
)
from financial_slides_worker.extraction.models import ExtractionLimits, FileSource

GENERIC_MEDIA_TYPES = {"", "application/octet-stream"}


def detect_media_type(data: bytes) -> str:
    if not data:
        raise EmptyInputError("The uploaded file is empty.")
    if b"%PDF-" in data[:1024]:
        return "application/pdf"
    raise UnsupportedFileError()


def validate_file_source(source: FileSource, limits: ExtractionLimits) -> str:
    if not source.file_name.strip():
        raise EmptyInputError("A file name is required for uploaded input.")
    if len(source.data) > limits.max_file_bytes:
        raise ExtractionLimitError(
            "file_too_large",
            f"The file exceeds the {limits.max_file_bytes}-byte limit.",
        )

    detected = detect_media_type(source.data)
    declared = (source.declared_media_type or "").lower()
    if declared not in GENERIC_MEDIA_TYPES and declared != detected:
        raise MediaTypeMismatchError(detected, source.declared_media_type or "")
    return detected
