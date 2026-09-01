"""Bounded local OCR and deterministic page-quality scoring."""

from __future__ import annotations

from collections.abc import Callable
import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
import re
import subprocess
from time import perf_counter
from typing import Any, Protocol

from financial_slides_worker.extraction.models import ExtractionContext, ExtractionLimits

BoundingBox = tuple[float, float, float, float]
_NUMBER = re.compile(r"^[($€£]?[+-]?\d[\d,.]*[kKmMbB]?%?[)]?$")
_ALLOWED_PUNCTUATION = set(".,:;!?%$€£+-/()[]{}'\"&")


@dataclass(frozen=True)
class OcrWord:
    text: str
    box: BoundingBox
    confidence: float
    line: tuple[int, int, int]


@dataclass(frozen=True)
class OcrTableCell:
    row: int
    column: int
    text: str
    box: BoundingBox
    confidence: float


@dataclass(frozen=True)
class OcrTable:
    cells: tuple[OcrTableCell, ...]
    box: BoundingBox
    row_count: int
    column_count: int
    confidence: float


@dataclass(frozen=True)
class OcrPage:
    words: tuple[OcrWord, ...]
    width_px: int
    height_px: int
    language: str
    tables: tuple[OcrTable, ...] = ()


@dataclass(frozen=True)
class RasterizedPage:
    """Encoded image input accepted by local OCR engines."""

    data: bytes
    width_px: int
    height_px: int


@dataclass(frozen=True)
class OcrImageLimits:
    max_image_bytes: int = 25 * 1024 * 1024
    max_pixels: int = 50_000_000
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_image_bytes < 1:
            raise ValueError("OCR image byte limit must be positive.")
        if self.max_pixels < 1:
            raise ValueError("OCR image pixel limit must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("OCR timeout must be positive.")


def _validate_rasterized_page(image: RasterizedPage, limits: OcrImageLimits) -> None:
    if not image.data:
        raise ValueError("OCR image data must not be empty.")
    if image.width_px <= 0 or image.height_px <= 0:
        raise ValueError("OCR image dimensions must be positive.")
    if len(image.data) > limits.max_image_bytes:
        raise ValueError(f"OCR image exceeds the {limits.max_image_bytes}-byte limit.")
    if image.width_px * image.height_px > limits.max_pixels:
        raise ValueError(f"OCR image exceeds the {limits.max_pixels}-pixel limit.")


class PageRasterizer(Protocol):
    def rasterize(self, page: Any) -> RasterizedPage: ...


class PdfPageRasterizer:
    """Replaceable pdfplumber page-to-PNG adapter."""

    def __init__(self, resolution: int = 144) -> None:
        if resolution < 72 or resolution > 600:
            raise ValueError("OCR raster resolution must be between 72 and 600 DPI.")
        self._resolution = resolution

    def rasterize(self, page: Any) -> RasterizedPage:
        image = page.to_image(resolution=self._resolution, antialias=True).original
        payload = BytesIO()
        image.save(payload, format="PNG")
        return RasterizedPage(payload.getvalue(), image.width, image.height)


@dataclass(frozen=True)
class PageQuality:
    text_coverage: float
    ocr_confidence: float
    suspicious_character_ratio: float
    table_structure: float
    numeric_consistency: float
    score: float


class OcrEngine(Protocol):
    provider: str

    def extract(self, page: Any, context: ExtractionContext) -> OcrPage: ...


class ImageOcrEngine(Protocol):
    provider: str

    def extract_image(
        self,
        image: RasterizedPage,
        context: ExtractionContext,
    ) -> OcrPage: ...


class OcrFailure(RuntimeError):
    """A local OCR page could not be processed safely."""


def parse_tesseract_tsv(
    tsv: str,
    width_px: int,
    height_px: int,
    language: str = "en",
) -> OcrPage:
    words = []
    for row in csv.DictReader(StringIO(tsv), delimiter="\t"):
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf") or -1)
        except ValueError:
            continue
        if not text or confidence < 0:
            continue
        try:
            left = float(row["left"])
            top = float(row["top"])
            right = left + float(row["width"])
            bottom = top + float(row["height"])
            line = (
                int(row["block_num"]),
                int(row["par_num"]),
                int(row["line_num"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        words.append(
            OcrWord(
                text=text,
                box=(left, top, right, bottom),
                confidence=max(0.0, min(1.0, confidence / 100)),
                line=line,
            )
        )
    return OcrPage(tuple(words), width_px, height_px, language)


class TesseractOcrEngine:
    """Bounded adapter around local Tesseract TSV output.

    The rasterizer is injected so the engine can be embedded in another PDF or
    image pipeline without importing pdfplumber-specific types.
    """

    provider = "tesseract"

    def __init__(
        self,
        executable: str = "tesseract",
        language: str = "eng",
        *,
        page_segmentation_mode: int = 1,
        rasterizer: PageRasterizer | None = None,
        image_limits: OcrImageLimits | None = None,
    ) -> None:
        if not executable.strip():
            raise ValueError("Tesseract executable must not be empty.")
        if not language.strip():
            raise ValueError("OCR language must not be empty.")
        if page_segmentation_mode < 0 or page_segmentation_mode > 13:
            raise ValueError("Tesseract page segmentation mode must be between 0 and 13.")
        self._executable = executable
        self._language = language
        self._page_segmentation_mode = page_segmentation_mode
        self._rasterizer = rasterizer or PdfPageRasterizer()
        self._image_limits = image_limits or OcrImageLimits()

    def extract(self, page: Any, context: ExtractionContext) -> OcrPage:
        context.ensure_time_remaining()
        return self.extract_image(self._rasterizer.rasterize(page), context)

    def extract_image(
        self,
        image: RasterizedPage,
        context: ExtractionContext,
    ) -> OcrPage:
        """OCR an encoded image without requiring a PDF page object."""

        _validate_rasterized_page(image, self._image_limits)
        context.ensure_time_remaining()
        try:
            result = subprocess.run(
                [
                    self._executable,
                    "stdin",
                    "stdout",
                    "-l",
                    self._language,
                    "--psm",
                    str(self._page_segmentation_mode),
                    "tsv",
                ],
                input=image.data,
                capture_output=True,
                check=True,
                timeout=context.seconds_remaining(),
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise OcrFailure("The local OCR engine failed or exceeded its time limit.") from exc
        context.ensure_time_remaining()
        return parse_tesseract_tsv(
            result.stdout.decode("utf-8", errors="replace"),
            image.width_px,
            image.height_px,
            self._language,
        )


class LocalOcrService:
    """Small public facade for embedding bounded local OCR in another system."""

    def __init__(
        self,
        engine: ImageOcrEngine | None = None,
        *,
        limits: OcrImageLimits | None = None,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._limits = limits or OcrImageLimits()
        self._engine = engine or TesseractOcrEngine(image_limits=self._limits)
        self._clock = clock

    @property
    def provider(self) -> str:
        return self._engine.provider

    def extract_image(self, data: bytes, width_px: int, height_px: int) -> OcrPage:
        image = RasterizedPage(data, width_px, height_px)
        _validate_rasterized_page(image, self._limits)
        started = self._clock()
        context = ExtractionContext(
            limits=ExtractionLimits(timeout_seconds=self._limits.timeout_seconds),
            deadline=started + self._limits.timeout_seconds,
            clock=self._clock,
        )
        return self._engine.extract_image(image, context)


def page_quality(page: OcrPage) -> PageQuality:
    text = "".join(word.text for word in page.words)
    page_area = max(1.0, float(page.width_px * page.height_px))
    covered_area = sum(
        max(0.0, min(page.width_px, right) - max(0.0, left))
        * max(0.0, min(page.height_px, bottom) - max(0.0, top))
        for left, top, right, bottom in (word.box for word in page.words)
    )
    text_coverage = min(1.0, covered_area / page_area)
    ocr_confidence = (
        sum(word.confidence for word in page.words) / len(page.words) if page.words else 0.0
    )
    suspicious = sum(
        not (character.isalnum() or character.isspace() or character in _ALLOWED_PUNCTUATION)
        for character in text
    )
    suspicious_ratio = suspicious / max(1, len(text))
    numeric_tokens = [word.text for word in page.words if any(char.isdigit() for char in word.text)]
    numeric_consistency = (
        sum(bool(_NUMBER.match(token)) for token in numeric_tokens) / len(numeric_tokens)
        if numeric_tokens
        else 1.0
    )
    table_structure = (
        sum(
            table.confidence
            for table in page.tables
            if table.row_count > 0 and table.column_count > 0 and table.cells
        )
        / len(page.tables)
        if page.tables
        else 1.0
    )
    normalized_coverage = min(1.0, text_coverage / 0.05)
    score = (
        0.25 * normalized_coverage
        + 0.4 * ocr_confidence
        + 0.15 * (1 - suspicious_ratio)
        + 0.1 * table_structure
        + 0.1 * numeric_consistency
    )
    return PageQuality(
        text_coverage=round(text_coverage, 4),
        ocr_confidence=round(ocr_confidence, 4),
        suspicious_character_ratio=round(suspicious_ratio, 4),
        table_structure=round(table_structure, 4),
        numeric_consistency=round(numeric_consistency, 4),
        score=round(max(0.0, min(1.0, score)), 4),
    )
