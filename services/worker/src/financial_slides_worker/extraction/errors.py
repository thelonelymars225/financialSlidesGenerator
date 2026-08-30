"""Typed failures returned by the extraction boundary."""


class ExtractionError(Exception):
    """Base failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EmptyInputError(ExtractionError):
    def __init__(self, message: str = "The source contains no extractable input.") -> None:
        super().__init__("empty_input", message)


class UnsupportedFileError(ExtractionError):
    def __init__(self, message: str = "The file signature is not supported.") -> None:
        super().__init__("unsupported_file", message)


class MediaTypeMismatchError(ExtractionError):
    def __init__(self, detected: str, declared: str) -> None:
        super().__init__(
            "media_type_mismatch",
            f"Detected media type {detected!r} does not match declared type {declared!r}.",
        )


class CorruptFileError(ExtractionError):
    def __init__(self, message: str = "The file is corrupt or cannot be parsed.") -> None:
        super().__init__("corrupt_file", message)


class EncryptedFileError(ExtractionError):
    def __init__(self, message: str = "Encrypted documents are not supported.") -> None:
        super().__init__("encrypted_file", message)


class OcrFailedError(ExtractionError):
    def __init__(
        self,
        message: str = "The document contains no extractable content after local OCR.",
    ) -> None:
        super().__init__("ocr_failed", message)


class ExtractionLimitError(ExtractionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class ExtractionTimeoutError(ExtractionError):
    def __init__(self, message: str = "Native extraction exceeded its time limit.") -> None:
        super().__init__("extraction_timeout", message)
