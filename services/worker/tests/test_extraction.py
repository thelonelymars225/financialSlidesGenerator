from __future__ import annotations

from base64 import b64decode
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont
import pypdfium2
import pytest

from financial_slides_worker.extraction import (
    EmptyInputError,
    EncryptedFileError,
    ExtractionError,
    ExtractionLimitError,
    ExtractionLimits,
    ExtractionService,
    ExtractionTimeoutError,
    FallbackReason,
    FileSource,
    MediaTypeMismatchError,
    OcrFailedError,
    ProviderPageResult,
    SelectivePageFallback,
    TextSource,
    UnsupportedFileError,
)
from financial_slides_worker.extraction.native import PdfPlumberExtractor, _page_blocks, _page_route
from financial_slides_worker.extraction.ocr import (
    OcrFailure,
    OcrPage,
    OcrTable,
    OcrTableCell,
    OcrWord,
    TesseractOcrEngine,
    page_quality,
    parse_tesseract_tsv,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPOSITORY_ROOT = Path(__file__).parents[3]


def fixture_bytes(name: str) -> bytes:
    return b64decode((FIXTURES / name).read_text(encoding="ascii"))


def validate_contract(document: dict[str, object], tmp_path: Path) -> None:
    document_path = tmp_path / "extracted-document.json"
    document_path.write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    script = """
import { readFile } from "node:fs/promises";
import { validateContract } from "./packages/contracts/scripts/contract-validation.mjs";
const value = JSON.parse(await readFile(process.argv.at(-1), "utf8"));
const result = await validateContract("extractedDocument", value);
if (!result.valid) {
  console.error(result.errors.join("\\n"));
  process.exit(1);
}
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, str(document_path)],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def scanned_pdf(text: str, *, size: tuple[int, int] = (600, 800), rotation: int = 0) -> bytes:
    image = Image.new("RGB", size, "white")
    font_size = max(12, min(size) // 12)
    font = ImageFont.truetype("DejaVuSans.ttf", font_size)
    ImageDraw.Draw(image).text(
        (max(5, font_size), max(5, font_size * 2)), text, fill="black", font=font
    )
    if rotation:
        image = image.rotate(rotation, expand=True)
    output = BytesIO()
    image.save(output, format="PDF", resolution=144)
    return output.getvalue()


def mixed_pdf(native: bytes, scan: bytes) -> bytes:
    destination = pypdfium2.PdfDocument.new()
    sources = [pypdfium2.PdfDocument(native), pypdfium2.PdfDocument(scan)]
    for source in sources:
        destination.import_pages(source)
    output = BytesIO()
    destination.save(output)
    return output.getvalue()


def ocr_page(
    *,
    confidence: float = 0.94,
    text: str = "Operating expenses were $12.4m",
    width: int = 1200,
    height: int = 1600,
) -> OcrPage:
    words = tuple(
        OcrWord(
            token,
            (40 + index * 130, 100, 140 + index * 130, 140),
            confidence,
            (1, 1, 1),
        )
        for index, token in enumerate(text.split())
    )
    return OcrPage(words, width, height, "en")


class FakeOcrEngine:
    provider = "fixture-ocr"

    def __init__(self, outputs: list[OcrPage | Exception]) -> None:
        self.outputs = iter(outputs)
        self.calls = 0

    def extract(self, page: object, context: object) -> OcrPage:
        self.calls += 1
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return output


class FakeFallbackProvider:
    method = "document_api"
    name = "fixture-document-api"
    model = "fixture-v1"
    retains_data = False

    def __init__(self) -> None:
        self.requests = []

    def extract_page(self, request, *, timeout_seconds):
        self.requests.append(request)
        page = {
            **request.evidence_page,
            "blocks": [
                {
                    "id": f"page-{request.page_number}-document-api-text-1",
                    "type": "text",
                    "order": 0,
                    "text": "Corrected operating expenses were $12.4m",
                    "source": {
                        "sourceId": request.evidence_page["blocks"][0]["source"]["sourceId"],
                        "pageNumber": request.page_number,
                        "sectionPath": [f"Page {request.page_number}"],
                    },
                    "confidence": 0.96,
                    "extraction": {
                        "method": self.method,
                        "provider": self.name,
                        "model": self.model,
                    },
                    "warnings": [],
                }
            ],
        }
        return ProviderPageResult(
            page,
            input_tokens=100,
            output_tokens=40,
            external_cost_usd=0.01,
        )


def test_pasted_text_emits_canonical_contract_with_zero_external_cost(
    tmp_path: Path,
) -> None:
    result = ExtractionService().extract_text(
        TextSource(text="Revenue increased to $12.4 million.")
    )

    assert result.document["schemaVersion"] == "0.1"
    assert result.document["source"]["inputType"] == "text"
    assert result.document["pages"][0]["blocks"][0]["text"].startswith("Revenue")
    assert result.telemetry.route == "pasted_text"
    assert result.telemetry.external_cost_usd == 0
    validate_contract(result.document, tmp_path)


def test_pdf_signature_routes_without_trusting_extension(tmp_path: Path) -> None:
    result = ExtractionService().extract_file(
        FileSource(
            data=fixture_bytes("native-financial-report.pdf.b64"),
            file_name="quarterly-report.bin",
            declared_media_type="application/octet-stream",
        )
    )

    page = result.document["pages"][0]
    text_blocks = [block for block in page["blocks"] if block["type"] == "text"]
    table_blocks = [block for block in page["blocks"] if block["type"] == "table"]

    assert result.document["source"]["mediaType"] == "application/pdf"
    assert result.document["source"]["fileName"] == "quarterly-report.bin"
    assert any("Quarterly revenue summary" in block["text"] for block in text_blocks)
    assert table_blocks[0]["rowCount"] == 3
    assert table_blocks[0]["columnCount"] == 2
    assert table_blocks[0]["cells"][-1]["text"] == "$12.4m"
    assert table_blocks[0]["source"]["boundingBox"]["unit"] == "pt"
    assert result.telemetry.route == "native_pdf"
    assert result.telemetry.external_cost_usd == 0
    validate_contract(result.document, tmp_path)


def test_partial_numeric_strip_table_falls_back_to_complete_row_text() -> None:
    class PartialTable:
        bbox = (300.0, 100.0, 370.0, 140.0)

    class PartialTablePage:
        width = 600.0

        def find_tables(self):
            return [PartialTable()]

        def extract_words(self, **kwargs):
            assert kwargs["y_tolerance"] == 3.0
            tokens = (
                ("Adjusted", 20, 106, 72),
                ("net", 78, 106, 98),
                ("income", 104, 106, 144),
                ("(TotalEnergies", 150, 106, 238),
                ("share)(1)", 244, 106, 294),
                ("7,770", 310, 100, 350),
                ("9,784", 420, 101, 460),
                ("-21%", 520, 101, 554),
            )
            return [
                {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 8}
                for text, x0, top, x1 in tokens
            ]

    blocks = _page_blocks(PartialTablePage(), "source-test", 10)

    assert not any(block["type"] == "table" for block in blocks)
    row = next(block for block in blocks if block["type"] == "text")
    assert row["text"] == (
        "Adjusted net income (TotalEnergies share)(1) 7,770 9,784 -21%"
    )
    assert row["source"]["boundingBox"] == {
        "left": 20.0,
        "top": 100.0,
        "right": 554.0,
        "bottom": 114.0,
        "unit": "pt",
    }


@pytest.mark.parametrize(
    ("source", "error_type", "code"),
    [
        (TextSource(text="   "), EmptyInputError, "empty_input"),
        (
            FileSource(data=b"not a PDF", file_name="report.pdf"),
            UnsupportedFileError,
            "unsupported_file",
        ),
        (
            FileSource(
                data=fixture_bytes("native-financial-report.pdf.b64"),
                file_name="report.pdf",
                declared_media_type="image/png",
            ),
            MediaTypeMismatchError,
            "media_type_mismatch",
        ),
        (
            FileSource(data=b"%PDF-1.7\nbroken", file_name="report.pdf"),
            ExtractionError,
            "corrupt_file",
        ),
        (
            FileSource(
                data=fixture_bytes("encrypted-financial-report.pdf.b64"),
                file_name="encrypted.pdf",
            ),
            EncryptedFileError,
            "encrypted_file",
        ),
    ],
)
def test_typed_failures(
    source: TextSource | FileSource,
    error_type: type[ExtractionError],
    code: str,
) -> None:
    service = ExtractionService()

    with pytest.raises(error_type) as raised:
        if isinstance(source, TextSource):
            service.extract_text(source)
        else:
            service.extract_file(source)

    assert raised.value.code == code


def test_file_and_page_limits_are_bounded() -> None:
    data = fixture_bytes("native-financial-report.pdf.b64")

    with pytest.raises(ExtractionLimitError, match="byte limit") as oversized:
        ExtractionService(limits=ExtractionLimits(max_file_bytes=10)).extract_file(
            FileSource(data=data, file_name="report.pdf")
        )
    assert oversized.value.code == "file_too_large"

    with pytest.raises(ExtractionLimitError, match="page limit") as too_many_pages:
        ExtractionService(limits=ExtractionLimits(max_pages=0)).extract_file(
            FileSource(data=data, file_name="report.pdf")
        )
    assert too_many_pages.value.code == "page_limit_exceeded"


def test_replaceable_parser_still_obeys_timeout_boundary() -> None:
    class FakeExtractor:
        media_type = "application/pdf"
        route = "fake_pdf"

        def extract(self, source: FileSource, context: object) -> dict[str, object]:
            return {}

    ticks = iter([0.0, 2.0])
    service = ExtractionService(
        extractors=(FakeExtractor(),),
        limits=ExtractionLimits(timeout_seconds=1),
        clock=lambda: next(ticks),
    )

    with pytest.raises(ExtractionTimeoutError) as raised:
        service.extract_file(FileSource(data=b"%PDF-1.7\nfixture", file_name="report.pdf"))
    assert raised.value.code == "extraction_timeout"


def test_page_router_distinguishes_native_scanned_and_mixed_content() -> None:
    native = [
        {
            "type": "text",
            "text": "Quarterly revenue increased and operating margin improved materially.",
            "source": {"boundingBox": {"left": 10, "top": 10, "right": 300, "bottom": 80}},
        }
    ]
    mixed = [
        {
            "type": "text",
            "text": "Page 2",
            "source": {"boundingBox": {"left": 10, "top": 10, "right": 50, "bottom": 20}},
        }
    ]

    assert _page_route(native, 612 * 792) == "born_digital"
    assert _page_route([], 612 * 792) == "scanned"
    assert _page_route(mixed, 612 * 792) == "mixed"


def test_clean_scan_uses_local_ocr_with_provenance_and_table_structure(
    tmp_path: Path,
) -> None:
    table = OcrTable(
        cells=(
            OcrTableCell(0, 0, "Metric", (40, 220, 200, 260), 0.96),
            OcrTableCell(0, 1, "Value", (220, 220, 380, 260), 0.95),
            OcrTableCell(1, 0, "Revenue", (40, 270, 200, 310), 0.94),
            OcrTableCell(1, 1, "$12.4m", (220, 270, 380, 310), 0.93),
        ),
        box=(40, 220, 380, 310),
        row_count=2,
        column_count=2,
        confidence=0.94,
    )
    output = ocr_page()
    output = OcrPage(output.words, output.width_px, output.height_px, "en", (table,))
    engine = FakeOcrEngine([output])
    service = ExtractionService(extractors=(PdfPlumberExtractor(engine),))

    result = service.extract_file(
        FileSource(data=scanned_pdf("Operating expenses were $12.4m"), file_name="scan.pdf")
    )

    blocks = result.document["pages"][0]["blocks"]
    assert engine.calls == 1
    assert blocks[0]["extraction"] == {
        "method": "ocr",
        "provider": "fixture-ocr",
        "model": "en",
    }
    assert [block["order"] for block in blocks] == list(range(len(blocks)))
    assert blocks[-1]["type"] == "table"
    assert blocks[-1]["cells"][-1]["text"] == "$12.4m"
    assert blocks[-1]["source"]["boundingBox"]["unit"] == "pt"
    assert any(warning["code"] == "page.route.scanned" for warning in result.document["warnings"])
    validate_contract(result.document, tmp_path)


def test_rotated_and_low_resolution_scans_remain_bounded_and_flag_low_quality(
    tmp_path: Path,
) -> None:
    low_quality = ocr_page(
        confidence=0.1,
        text="R��v��nu�� 12..4",
        width=160,
        height=120,
    )
    engine = FakeOcrEngine([low_quality])
    service = ExtractionService(extractors=(PdfPlumberExtractor(engine),))

    result = service.extract_file(
        FileSource(
            data=scanned_pdf("Revenue 12.4", size=(160, 120), rotation=90),
            file_name="rotated-low-resolution.pdf",
        )
    )

    block = result.document["pages"][0]["blocks"][0]
    box = block["source"]["boundingBox"]
    assert 0 <= box["left"] < box["right"] <= result.document["pages"][0]["width"]
    assert 0 <= box["top"] < box["bottom"] <= result.document["pages"][0]["height"]
    assert block["warnings"][0]["code"] == "ocr.low_confidence"
    assert any(warning["code"] == "ocr.low_confidence" for warning in result.document["warnings"])
    validate_contract(result.document, tmp_path)


def test_low_confidence_ocr_escalates_only_its_page_to_document_api(
    tmp_path: Path,
) -> None:
    engine = FakeOcrEngine([ocr_page(confidence=0.5)])
    provider = FakeFallbackProvider()
    extractor = PdfPlumberExtractor(
        engine,
        SelectivePageFallback((provider,)),
    )

    result = ExtractionService(extractors=(extractor,)).extract_file(
        FileSource(
            data=scanned_pdf("Operating expenses were $12.4m"),
            file_name="low-confidence.pdf",
        )
    )

    assert len(provider.requests) == 1
    assert provider.requests[0].reason is FallbackReason.OCR_LOW_CONFIDENCE
    assert provider.requests[0].page_number == 1
    assert provider.requests[0].image_png.startswith(b"\x89PNG")
    assert result.document["pages"][0]["blocks"][0]["extraction"]["method"] == "document_api"
    assert result.telemetry.route == "native_pdf+fallback"
    assert result.telemetry.external_cost_usd == 0.01
    assert any(
        warning["code"] == "fallback.applied.document_api"
        for warning in result.document["warnings"]
    )
    validate_contract(result.document, tmp_path)


def test_provider_is_not_called_without_an_explicit_fallback_reason() -> None:
    provider = FakeFallbackProvider()
    extractor = PdfPlumberExtractor(
        FakeOcrEngine([]),
        SelectivePageFallback((provider,)),
    )

    result = ExtractionService(extractors=(extractor,)).extract_file(
        FileSource(
            data=fixture_bytes("native-financial-report.pdf.b64"),
            file_name="native.pdf",
        )
    )

    assert provider.requests == []
    assert result.telemetry.route == "native_pdf"
    assert result.telemetry.external_cost_usd == 0


def test_mixed_pdf_routes_only_scanned_page_to_ocr(tmp_path: Path) -> None:
    engine = FakeOcrEngine([ocr_page()])
    service = ExtractionService(extractors=(PdfPlumberExtractor(engine),))
    source = mixed_pdf(
        fixture_bytes("native-financial-report.pdf.b64"),
        scanned_pdf("Operating expenses were $12.4m"),
    )

    result = service.extract_file(FileSource(data=source, file_name="mixed.pdf"))

    assert engine.calls == 1
    assert result.document["pages"][0]["blocks"][0]["extraction"]["method"] == "native_pdf"
    assert result.document["pages"][1]["blocks"][0]["extraction"]["method"] == "ocr"
    assert any(warning["code"] == "document.route.mixed" for warning in result.document["warnings"])
    validate_contract(result.document, tmp_path)


def test_image_only_ocr_failure_returns_typed_error() -> None:
    scan = scanned_pdf("Operating expenses were $12.4m")
    failed_engine = FakeOcrEngine([OcrFailure("fixture failure")])

    with pytest.raises(OcrFailedError) as raised:
        ExtractionService(extractors=(PdfPlumberExtractor(failed_engine),)).extract_file(
            FileSource(data=scan, file_name="failed.pdf")
        )

    assert raised.value.code == "ocr_failed"
    assert failed_engine.calls == 1


def test_ocr_page_limit_cannot_return_a_successful_empty_document() -> None:
    scan = scanned_pdf("Operating expenses were $12.4m")
    limited_engine = FakeOcrEngine([ocr_page()])

    with pytest.raises(OcrFailedError) as raised:
        ExtractionService(
            extractors=(PdfPlumberExtractor(limited_engine),),
            limits=ExtractionLimits(max_ocr_pages=0),
        ).extract_file(FileSource(data=scan, file_name="limited.pdf"))

    assert raised.value.code == "ocr_failed"
    assert limited_engine.calls == 0


def test_mixed_document_succeeds_when_decorative_page_ocr_fails(tmp_path: Path) -> None:
    engine = FakeOcrEngine([OcrFailure("fixture failure")])
    service = ExtractionService(extractors=(PdfPlumberExtractor(engine),))
    source = mixed_pdf(
        fixture_bytes("native-financial-report.pdf.b64"),
        scanned_pdf(""),
    )

    result = service.extract_file(FileSource(data=source, file_name="mixed-decorative.pdf"))

    assert engine.calls == 1
    assert result.document["pages"][0]["blocks"]
    assert result.document["pages"][1]["blocks"] == []
    assert any(warning["code"] == "ocr.failed" for warning in result.document["warnings"])
    assert any(
        warning["code"] == "page.no_extractable_content"
        for warning in result.document["warnings"]
    )
    validate_contract(result.document, tmp_path)


def test_tesseract_tsv_parser_and_quality_signals() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth"
        "\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t10\t20\t50\t15\t96.0\tRevenue\n"
        "5\t1\t1\t1\t1\t2\t70\t20\t45\t15\t92.0\t$12.4m\n"
        "5\t1\t1\t1\t2\t1\t10\t45\t30\t15\tbad\tignored\n"
    )

    page = parse_tesseract_tsv(tsv, 200, 100)
    quality = page_quality(page)

    assert [word.text for word in page.words] == ["Revenue", "$12.4m"]
    assert quality.ocr_confidence == 0.94
    assert quality.text_coverage > 0
    assert quality.suspicious_character_ratio == 0
    assert quality.numeric_consistency == 1


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="local Tesseract is unavailable")
def test_local_tesseract_adapter_reads_synthetic_scan() -> None:
    data = scanned_pdf("Revenue 12.4 million")
    service = ExtractionService(extractors=(PdfPlumberExtractor(TesseractOcrEngine()),))

    result = service.extract_file(FileSource(data=data, file_name="tesseract-scan.pdf"))

    assert any(
        "Revenue" in block.get("text", "") for block in result.document["pages"][0]["blocks"]
    )
