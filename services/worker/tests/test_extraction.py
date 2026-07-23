from __future__ import annotations

from base64 import b64decode
import json
from pathlib import Path
import subprocess

import pytest

from financial_slides_worker.extraction import (
    EmptyInputError,
    EncryptedFileError,
    ExtractionError,
    ExtractionLimitError,
    ExtractionLimits,
    ExtractionService,
    ExtractionTimeoutError,
    FileSource,
    MediaTypeMismatchError,
    TextSource,
    UnsupportedFileError,
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
