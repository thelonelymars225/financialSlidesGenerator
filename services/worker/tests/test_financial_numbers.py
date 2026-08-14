from financial_slides_worker.extraction.finance_numbers import enrich_financial_numbers
from financial_slides_worker.extraction.models import TextSource
from financial_slides_worker.extraction.service import ExtractionService


def test_pasted_text_preserves_currency_scale_and_period() -> None:
    result = ExtractionService().extract_text(
        TextSource("Revenue reached SAR 12.4 billion in FY2025.")
    )

    value = result.document["pages"][0]["blocks"][0]["numericValues"][0]

    assert value == {
        "displayedValue": "SAR 12.4 billion",
        "value": 12_400_000_000,
        "currency": "SAR",
        "scaleFactor": 1_000_000_000,
        "period": "FY2025",
    }


def test_table_values_inherit_header_financial_context() -> None:
    document = {
        "pages": [
            {
                "blocks": [
                    {
                        "type": "table",
                        "cells": [
                            {"row": 0, "column": 0, "text": ""},
                            {"row": 0, "column": 1, "text": "FY2025"},
                            {"row": 0, "column": 2, "text": "FY2024"},
                            {"row": 1, "column": 0, "text": "Revenue (SAR million)"},
                            {"row": 1, "column": 1, "text": "4,007"},
                            {"row": 1, "column": 2, "text": "(3,500)"},
                        ],
                    }
                ]
            }
        ]
    }

    enrich_financial_numbers(document)
    cells = document["pages"][0]["blocks"][0]["cells"]

    assert cells[4]["numericValue"] == {
        "displayedValue": "4,007",
        "value": 4_007_000_000,
        "currency": "SAR",
        "scaleFactor": 1_000_000,
        "period": "FY2025",
    }
    assert cells[5]["numericValue"] == {
        "displayedValue": "(3,500)",
        "value": -3_500_000_000,
        "currency": "SAR",
        "scaleFactor": 1_000_000,
        "period": "FY2024",
    }


def test_existing_structured_values_are_not_rewritten() -> None:
    document = {
        "pages": [
            {
                "blocks": [
                    {
                        "type": "text",
                        "text": "Revenue $12.4 million in Q2 2026",
                        "numericValues": [
                            {
                                "displayedValue": "$12.4 million",
                                "value": 12_400_000,
                                "currency": "USD",
                                "scaleFactor": 1_000_000,
                                "period": "Q2 2026",
                            }
                        ],
                    }
                ]
            }
        ]
    }

    before = document["pages"][0]["blocks"][0]["numericValues"].copy()
    enrich_financial_numbers(document)

    assert document["pages"][0]["blocks"][0]["numericValues"] == before
