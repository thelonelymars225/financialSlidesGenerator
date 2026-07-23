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


class PdfPlumberExtractor:
    media_type = "application/pdf"
    route = "native_pdf"

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
                for page_number, page in enumerate(pdf.pages, start=1):
                    context.ensure_time_remaining()
                    blocks = _page_blocks(page, source_id, page_number)
                    if not blocks:
                        warnings.append(
                            {
                                "code": "page.no_native_content",
                                "severity": "warning",
                                "message": (
                                    f"Page {page_number} has no native text or table content; "
                                    "it may require OCR."
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
