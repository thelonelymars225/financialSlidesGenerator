"""Deterministic pasted-text and born-digital PDF extraction."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from financial_slides_worker.extraction.errors import (
    CorruptFileError,
    EmptyInputError,
    EncryptedFileError,
    ExtractionError,
    ExtractionLimitError,
)
from financial_slides_worker.extraction.models import (
    CanonicalDocument,
    ExtractionContext,
    FileSource,
)
from financial_slides_worker.extraction.ocr import (
    OcrEngine,
    OcrFailure,
    OcrPage,
    TesseractOcrEngine,
    page_quality,
)

BoundingBox = tuple[float, float, float, float]


def _identity(content: bytes) -> tuple[str, str, str]:
    digest = sha256(content).hexdigest()
    return f"document-{digest[:16]}", f"source-{digest[:16]}", f"sha256:{digest}"


def _source_location(
    source_id: str,
    page_number: int,
    bounding_box: BoundingBox | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "sourceId": source_id,
        "pageNumber": page_number,
        "sectionPath": [f"Page {page_number}"],
    }
    if bounding_box is not None:
        left, top, right, bottom = bounding_box
        source["boundingBox"] = {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "unit": "pt",
        }
    return source


def extract_pasted_text(text: str) -> CanonicalDocument:
    normalized = text.strip()
    if not normalized:
        raise EmptyInputError()

    raw = normalized.encode("utf-8")
    document_id, source_id, content_hash = _identity(raw)
    return {
        "schemaVersion": "0.1",
        "documentId": document_id,
        "source": {
            "sourceId": source_id,
            "inputType": "text",
            "mediaType": "text/plain",
            "contentHash": content_hash,
        },
        "pages": [
            {
                "pageNumber": 1,
                "width": 612,
                "height": 792,
                "coordinateUnit": "pt",
                "blocks": [
                    {
                        "id": "page-1-text-1",
                        "type": "text",
                        "order": 0,
                        "text": normalized,
                        "source": {
                            "sourceId": source_id,
                            "pageNumber": 1,
                            "sectionPath": ["Pasted input"],
                        },
                        "confidence": 1.0,
                        "extraction": {"method": "pasted_text"},
                        "warnings": [],
                    }
                ],
            }
        ],
        "warnings": [],
    }


def _inside_any_table(word: dict[str, Any], table_boxes: list[BoundingBox]) -> bool:
    center_x = (float(word["x0"]) + float(word["x1"])) / 2
    center_y = (float(word["top"]) + float(word["bottom"])) / 2
    return any(
        left <= center_x <= right and top <= center_y <= bottom
        for left, top, right, bottom in table_boxes
    )


def _group_words_into_lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        if not lines or abs(float(lines[-1][0]["top"]) - float(word["top"])) > 3:
            lines.append([word])
        else:
            lines[-1].append(word)

    grouped: list[dict[str, Any]] = []
    for line in lines:
        ordered = sorted(line, key=lambda item: float(item["x0"]))
        grouped.append(
            {
                "text": " ".join(str(word["text"]) for word in ordered).strip(),
                "bbox": (
                    min(float(word["x0"]) for word in ordered),
                    min(float(word["top"]) for word in ordered),
                    max(float(word["x1"]) for word in ordered),
                    max(float(word["bottom"]) for word in ordered),
                ),
            }
        )
    return [line for line in grouped if line["text"]]


def _table_block(
    table: Any,
    source_id: str,
    page_number: int,
    block_index: int,
) -> dict[str, Any]:
    matrix = table.extract()
    row_count = len(table.rows)
    column_count = max((len(row.cells) for row in table.rows), default=0)
    cells = []
    for row_index, row in enumerate(table.rows):
        for column_index, cell_box in enumerate(row.cells):
            if cell_box is None:
                continue
            value = ""
            if row_index < len(matrix) and column_index < len(matrix[row_index]):
                value = matrix[row_index][column_index] or ""
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "rowSpan": 1,
                    "columnSpan": 1,
                    "text": value,
                    "confidence": 1.0,
                    "source": _source_location(source_id, page_number, cell_box),
                }
            )

    return {
        "id": f"page-{page_number}-table-{block_index}",
        "type": "table",
        "order": 0,
        "rowCount": row_count,
        "columnCount": column_count,
        "cells": cells,
        "source": _source_location(source_id, page_number, table.bbox),
        "confidence": 1.0,
        "extraction": {"method": "native_pdf", "provider": "pdfplumber"},
        "warnings": [],
    }


def _page_blocks(page: Any, source_id: str, page_number: int) -> list[dict[str, Any]]:
    tables = page.find_tables()
    table_boxes = [tuple(float(value) for value in table.bbox) for table in tables]
    words = page.extract_words(
        x_tolerance=2,
        y_tolerance=3,
        keep_blank_chars=False,
        use_text_flow=True,
    )
    lines = _group_words_into_lines(
        [word for word in words if not _inside_any_table(word, table_boxes)]
    )

    ordered_items: list[tuple[float, float, dict[str, Any]]] = []
    for index, line in enumerate(lines, start=1):
        bbox = line["bbox"]
        block = {
            "id": f"page-{page_number}-text-{index}",
            "type": "text",
            "order": 0,
            "text": line["text"],
            "source": _source_location(source_id, page_number, bbox),
            "confidence": 1.0,
            "extraction": {"method": "native_pdf", "provider": "pdfplumber"},
            "warnings": [],
        }
        ordered_items.append((bbox[1], bbox[0], block))

    for index, table in enumerate(tables, start=1):
        block = _table_block(table, source_id, page_number, index)
        ordered_items.append((float(table.bbox[1]), float(table.bbox[0]), block))

    ordered_items.sort(key=lambda item: (item[0], item[1]))
    blocks = [item[2] for item in ordered_items]
    for order, block in enumerate(blocks):
        block["order"] = order
    return blocks


def _block_text(block: dict[str, Any]) -> str:
    if block["type"] == "text":
        return str(block["text"])
    if block["type"] == "table":
        return " ".join(str(cell["text"]) for cell in block["cells"])
    return ""


def _page_route(blocks: list[dict[str, Any]], page_area: float) -> str:
    useful_characters = sum(
        character.isalnum() for block in blocks for character in _block_text(block)
    )
    covered_area = 0.0
    for block in blocks:
        box = block["source"].get("boundingBox")
        if box:
            covered_area += max(0.0, box["right"] - box["left"]) * max(
                0.0, box["bottom"] - box["top"]
            )
    if useful_characters == 0:
        return "scanned"
    if useful_characters < 40 or covered_area / max(1.0, page_area) < 0.01:
        return "mixed"
    return "born_digital"


def _scale_box(
    box: BoundingBox,
    ocr_page: OcrPage,
    page_width: float,
    page_height: float,
) -> BoundingBox:
    scale_x = page_width / max(1, ocr_page.width_px)
    scale_y = page_height / max(1, ocr_page.height_px)
    left, top, right, bottom = box
    return (
        max(0.0, min(page_width, left * scale_x)),
        max(0.0, min(page_height, top * scale_y)),
        max(0.0, min(page_width, right * scale_x)),
        max(0.0, min(page_height, bottom * scale_y)),
    )


def _ocr_blocks(
    ocr_page: OcrPage,
    source_id: str,
    page_number: int,
    page_width: float,
    page_height: float,
    provider: str,
) -> tuple[list[dict[str, Any]], float]:
    quality = page_quality(ocr_page)
    warning = {
        "code": "ocr.low_confidence",
        "severity": "warning",
        "message": f"Page {page_number} OCR quality score is {quality.score:.2f}; review required.",
    }
    block_warnings = [warning] if quality.score < 0.65 else []
    ordered_items: list[tuple[float, float, dict[str, Any]]] = []

    lines: dict[tuple[int, int, int], list[Any]] = {}
    for word in ocr_page.words:
        lines.setdefault(word.line, []).append(word)
    for index, words in enumerate(lines.values(), start=1):
        ordered = sorted(words, key=lambda word: word.box[0])
        box = (
            min(word.box[0] for word in ordered),
            min(word.box[1] for word in ordered),
            max(word.box[2] for word in ordered),
            max(word.box[3] for word in ordered),
        )
        scaled_box = _scale_box(box, ocr_page, page_width, page_height)
        block = {
            "id": f"page-{page_number}-ocr-text-{index}",
            "type": "text",
            "order": 0,
            "text": " ".join(word.text for word in ordered),
            "source": _source_location(source_id, page_number, scaled_box),
            "confidence": round(sum(word.confidence for word in ordered) / len(ordered), 4),
            "extraction": {
                "method": "ocr",
                "provider": provider,
                "model": ocr_page.language,
            },
            "warnings": block_warnings,
        }
        ordered_items.append((scaled_box[1], scaled_box[0], block))

    for index, table in enumerate(ocr_page.tables, start=1):
        cells = [
            {
                "row": cell.row,
                "column": cell.column,
                "rowSpan": 1,
                "columnSpan": 1,
                "text": cell.text,
                "confidence": cell.confidence,
                "source": _source_location(
                    source_id,
                    page_number,
                    _scale_box(cell.box, ocr_page, page_width, page_height),
                ),
            }
            for cell in table.cells
        ]
        scaled_box = _scale_box(table.box, ocr_page, page_width, page_height)
        block = {
            "id": f"page-{page_number}-ocr-table-{index}",
            "type": "table",
            "order": 0,
            "rowCount": table.row_count,
            "columnCount": table.column_count,
            "cells": cells,
            "source": _source_location(source_id, page_number, scaled_box),
            "confidence": table.confidence,
            "extraction": {
                "method": "ocr",
                "provider": provider,
                "model": ocr_page.language,
            },
            "warnings": block_warnings,
        }
        ordered_items.append((scaled_box[1], scaled_box[0], block))

    ordered_items.sort(key=lambda item: (item[0], item[1]))
    blocks = [item[2] for item in ordered_items]
    for order, block in enumerate(blocks):
        block["order"] = order
    return blocks, quality.score


class PdfPlumberExtractor:
    media_type = "application/pdf"
    route = "native_pdf"

    def __init__(self, ocr_engine: OcrEngine | None = None) -> None:
        self._ocr_engine = ocr_engine or TesseractOcrEngine()

    def extract(
        self,
        source: FileSource,
        context: ExtractionContext,
    ) -> CanonicalDocument:
        context.ensure_time_remaining()
        document_id, source_id, content_hash = _identity(source.data)
        warnings: list[dict[str, str]] = []

        try:
            with pdfplumber.open(BytesIO(source.data)) as pdf:
                if not pdf.doc.is_extractable:
                    raise EncryptedFileError()
                if not pdf.pages:
                    raise CorruptFileError("The PDF contains no pages.")
                if len(pdf.pages) > context.limits.max_pages:
                    raise ExtractionLimitError(
                        "page_limit_exceeded",
                        f"The PDF exceeds the {context.limits.max_pages}-page limit.",
                    )

                pages = []
                ocr_pages = 0
                page_routes: set[str] = set()
                for page_number, page in enumerate(pdf.pages, start=1):
                    context.ensure_time_remaining()
                    blocks = _page_blocks(page, source_id, page_number)
                    page_route = _page_route(
                        blocks,
                        float(page.width) * float(page.height),
                    )
                    page_routes.add(page_route)
                    if page_route != "born_digital":
                        if ocr_pages >= context.limits.max_ocr_pages:
                            warnings.append(
                                {
                                    "code": "ocr.page_limit_exceeded",
                                    "severity": "error",
                                    "message": (
                                        f"Page {page_number} requires OCR but the "
                                        f"{context.limits.max_ocr_pages}-page OCR limit was reached."
                                    ),
                                }
                            )
                        else:
                            ocr_pages += 1
                            try:
                                ocr_page = self._ocr_engine.extract(page, context)
                                ocr_blocks, quality_score = _ocr_blocks(
                                    ocr_page,
                                    source_id,
                                    page_number,
                                    float(page.width),
                                    float(page.height),
                                    self._ocr_engine.provider,
                                )
                                if ocr_blocks:
                                    blocks = ocr_blocks
                                warnings.append(
                                    {
                                        "code": f"page.route.{page_route}",
                                        "severity": "info",
                                        "message": (
                                            f"Page {page_number} used local OCR after "
                                            f"{page_route} detection."
                                        ),
                                    }
                                )
                                if quality_score < 0.65:
                                    warnings.append(
                                        {
                                            "code": "ocr.low_confidence",
                                            "severity": "warning",
                                            "message": (
                                                f"Page {page_number} OCR quality score is "
                                                f"{quality_score:.2f}; review required."
                                            ),
                                        }
                                    )
                            except OcrFailure:
                                warnings.append(
                                    {
                                        "code": "ocr.failed",
                                        "severity": "error",
                                        "message": (
                                            f"Local OCR failed for page {page_number}; "
                                            "manual review is required."
                                        ),
                                    }
                                )
                    if not blocks:
                        warnings.append(
                            {
                                "code": "page.no_extractable_content",
                                "severity": "error",
                                "message": (
                                    f"Page {page_number} has no extractable text or table content."
                                ),
                            }
                        )
                    pages.append(
                        {
                            "pageNumber": page_number,
                            "width": float(page.width),
                            "height": float(page.height),
                            "coordinateUnit": "pt",
                            "blocks": blocks,
                        }
                    )
                if "born_digital" in page_routes and page_routes.intersection({"scanned", "mixed"}):
                    warnings.append(
                        {
                            "code": "document.route.mixed",
                            "severity": "info",
                            "message": "The document combines native and local OCR page routes.",
                        }
                    )
        except PDFPasswordIncorrect as exc:
            raise EncryptedFileError() from exc
        except PdfminerException as exc:
            if exc.args and isinstance(exc.args[0], PDFPasswordIncorrect):
                raise EncryptedFileError() from exc
            raise CorruptFileError() from exc
        except ExtractionError:
            raise
        except Exception as exc:
            raise CorruptFileError() from exc

        context.ensure_time_remaining()
        return {
            "schemaVersion": "0.1",
            "documentId": document_id,
            "source": {
                "sourceId": source_id,
                "inputType": "file",
                "mediaType": self.media_type,
                "fileName": Path(source.file_name).name,
                "contentHash": content_hash,
            },
            "pages": pages,
            "warnings": warnings,
        }
