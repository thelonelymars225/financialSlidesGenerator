from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from financial_slides_worker.extraction.finance import enrich_financial_facts

FIXTURES = Path(__file__).parent / "fixtures"
REPOSITORY_ROOT = Path(__file__).parents[3]


def _document(rows: list[list[str]], section_path: list[str]) -> dict[str, object]:
    cells = []
    for row_index, row in enumerate(rows):
        for column_index, text in enumerate(row):
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "rowSpan": 1,
                    "columnSpan": 1,
                    "text": text,
                    "confidence": 0.98,
                    "source": {
                        "sourceId": "source-finance-fixture",
                        "pageNumber": 1,
                        "sectionPath": section_path,
                    },
                }
            )
    return {
        "schemaVersion": "0.1",
        "documentId": "document-finance-fixture",
        "source": {
            "sourceId": "source-finance-fixture",
            "inputType": "file",
            "mediaType": "application/pdf",
            "fileName": "finance-fixture.pdf",
        },
        "pages": [
            {
                "pageNumber": 1,
                "width": 612,
                "height": 792,
                "coordinateUnit": "pt",
                "blocks": [
                    {
                        "id": "table-finance-fixture",
                        "type": "table",
                        "order": 0,
                        "rowCount": len(rows),
                        "columnCount": max(len(row) for row in rows),
                        "cells": cells,
                        "source": {
                            "sourceId": "source-finance-fixture",
                            "pageNumber": 1,
                            "sectionPath": section_path,
                        },
                        "confidence": 0.98,
                        "extraction": {"method": "native_pdf", "provider": "fixture"},
                        "warnings": [],
                    }
                ],
            }
        ],
        "warnings": [],
    }


def _validate_contract(document: dict[str, object], tmp_path: Path) -> None:
    document_path = tmp_path / "extracted-document-v0.2.json"
    document_path.write_text(json.dumps(document), encoding="utf-8")
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


@pytest.mark.parametrize(
    "case",
    json.loads((FIXTURES / "finance-aware-cases.json").read_text(encoding="utf-8")),
    ids=lambda case: case["name"],
)
def test_representative_financial_fact_fixtures(case: dict[str, object], tmp_path: Path) -> None:
    result = enrich_financial_facts(_document(case["rows"], case["sectionPath"]))
    facts = result["financialFacts"]

    assert result["schemaVersion"] == "0.2"
    assert len(facts) == case["expectedFactCount"]
    assert {fact["statementType"] for fact in facts} == {case["expectedStatementType"]}
    assert facts[-1]["period"]["label"] == case["expectedPeriod"]
    assert facts[-1]["normalizedValue"] == case["expectedNormalizedValue"]
    if currency := case.get("expectedCurrency"):
        assert {fact["currency"] for fact in facts} == {currency}
    if unit := case.get("expectedUnit"):
        assert {fact["unit"] for fact in facts} == {unit}
    if segment := case.get("expectedSegment"):
        assert {fact["scope"]["segment"] for fact in facts} == {segment}
    if status := case.get("expectedRestatementStatus"):
        assert {fact["restatementStatus"] for fact in facts} == {status}
    if scenarios := case.get("expectedScenarios"):
        assert [fact["scenario"] for fact in facts] == scenarios
    _validate_contract(result, tmp_path)


def test_ambiguous_values_keep_raw_text_and_field_level_warnings(tmp_path: Path) -> None:
    result = enrich_financial_facts(
        _document(
            [["Metric", "Value"], ["Revenue", "12,4?"], ["Operating margin", "—"]],
            ["KPI table"],
        )
    )

    assert [fact["displayedValue"] for fact in result["financialFacts"]] == ["12,4?", "—"]
    assert all(fact["parsedValue"] is None for fact in result["financialFacts"])
    assert all(fact["confidence"]["parsedValue"] == 0 for fact in result["financialFacts"])
    assert {finding["code"] for finding in result["factValidation"]} >= {
        "numeric.parse_failed",
        "period.missing",
        "unit.missing",
    }
    _validate_contract(result, tmp_path)

    broken_header = enrich_financial_facts(_document([["", ""], ["", "12.4"]], ["Financial table"]))
    assert "header.mapping_broken" in {
        finding["code"] for finding in broken_header["factValidation"]
    }


def test_duplicate_conflict_and_total_reconciliation_are_preserved() -> None:
    duplicate = enrich_financial_facts(
        _document(
            [
                ["Metric", "Q2 2026"],
                ["Revenue (USD millions)", "12.4"],
                ["Revenue (USD millions)", "12.4"],
                ["Revenue (USD millions)", "13.0"],
            ],
            ["Income statement"],
        )
    )
    assert {finding["code"] for finding in duplicate["factValidation"]} >= {
        "fact.duplicate",
        "fact.conflict",
    }
    assert duplicate["financialFacts"][1]["relations"]["duplicateOf"]
    assert duplicate["financialFacts"][2]["relations"]["conflictsWith"]

    unit_conflict = enrich_financial_facts(
        _document(
            [
                ["Metric", "Q2 2026"],
                ["Revenue (USD millions)", "12.4"],
                ["Revenue (SAR millions)", "12.4"],
            ],
            ["Income statement"],
        )
    )
    assert "unit.conflict" in {finding["code"] for finding in unit_conflict["factValidation"]}

    totals = enrich_financial_facts(
        _document(
            [
                ["Metric", "FY 2025"],
                ["Product A (USD millions)", "4"],
                ["Product B (USD millions)", "5"],
                ["Total revenue (USD millions)", "10"],
            ],
            ["Income statement"],
        )
    )
    assert "total.unreconciled" in {finding["code"] for finding in totals["factValidation"]}


def test_golden_case_retrieves_required_facts_without_raw_page_access() -> None:
    result = enrich_financial_facts(
        _document(
            [
                ["Metric", "Actual Q1 2026", "Actual Q2 2026"],
                ["Revenue (USD millions)", "10.0", "12.4"],
                ["Operating margin", "16%", "18%"],
            ],
            ["Income statement", "KPI summary"],
        )
    )

    index = {
        (fact["metric"]["id"], fact["period"]["label"]): fact for fact in result["financialFacts"]
    }
    revenue = index[("revenue", "Q2 2026")]
    margin = index[("operating-margin", "Q2 2026")]

    assert revenue["normalizedValue"] == 12_400_000
    assert revenue["currency"] == "USD"
    assert margin["normalizedValue"] == 0.18
    assert revenue["evidence"]["headerPath"]
    assert margin["evidence"]["tableId"] == "table-finance-fixture"


def test_merged_multirow_headers_and_footnotes_keep_lineage(tmp_path: Path) -> None:
    document = _document(
        [
            ["", "Actual", ""],
            ["Metric", "Q1 2026", "Q2 2026"],
            ["Revenue", "$10.0m*", "$12.4m†"],
        ],
        ["Income statement"],
    )
    cells = document["pages"][0]["blocks"][0]["cells"]
    merged_header = next(cell for cell in cells if (cell["row"], cell["column"]) == (0, 1))
    merged_header["columnSpan"] = 2
    cells.remove(next(cell for cell in cells if (cell["row"], cell["column"]) == (0, 2)))

    result = enrich_financial_facts(document)

    assert [fact["displayedValue"] for fact in result["financialFacts"]] == [
        "$10.0m*",
        "$12.4m†",
    ]
    assert [fact["normalizedValue"] for fact in result["financialFacts"]] == [
        10_000_000,
        12_400_000,
    ]
    assert all("Actual" in fact["evidence"]["headerPath"] for fact in result["financialFacts"])
    assert {fact["scenario"] for fact in result["financialFacts"]} == {"actual"}
    _validate_contract(result, tmp_path)
