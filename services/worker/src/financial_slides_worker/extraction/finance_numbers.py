"""Small deterministic enrichment for financial numeric context."""

from __future__ import annotations

import re
from typing import Any

CURRENCY_CODES = {"USD", "SAR", "AED", "QAR", "KWD", "BHD", "OMR", "EUR", "GBP"}
CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}
SCALE_FACTORS = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
}

_NUMBER = re.compile(
    r"(?<!\w)(?P<open>\()?\s*"
    r"(?P<currency>\$|€|£|USD|SAR|AED|QAR|KWD|BHD|OMR|EUR|GBP)?\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<suffix>%|bn|mn|m|k|billion|million|thousand)?\s*"
    r"(?P<close>\))?(?!\w)",
    flags=re.IGNORECASE,
)
_PERIOD_PATTERNS = (
    re.compile(r"\bQ[1-4]\s*20\d{2}\b", flags=re.IGNORECASE),
    re.compile(r"\bFY\s*20\d{2}\b", flags=re.IGNORECASE),
    re.compile(r"\bH[12]\s*20\d{2}\b", flags=re.IGNORECASE),
    re.compile(r"\b6M\s*20\d{2}\b", flags=re.IGNORECASE),
    re.compile(r"\b20\d{2}\b"),
)
_SCALE = re.compile(r"\b(billion|million|thousand|bn|mn|m|k)\b", flags=re.IGNORECASE)
_CURRENCY = re.compile(r"\b(USD|SAR|AED|QAR|KWD|BHD|OMR|EUR|GBP)\b", flags=re.IGNORECASE)


def _period(text: str) -> str | None:
    for pattern in _PERIOD_PATTERNS:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    return None


def _period_spans(text: str) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for pattern in _PERIOD_PATTERNS:
        spans.extend(match.span() for match in pattern.finditer(text))
    return tuple(spans)


def _currency(text: str) -> str | None:
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    match = _CURRENCY.search(text)
    if not match:
        return None
    code = match.group(1).upper()
    return code if code in CURRENCY_CODES else None


def _scale(text: str) -> int | None:
    match = _SCALE.search(text)
    return SCALE_FACTORS.get(match.group(1).lower()) if match else None


def _numbers(text: str, context: str = "") -> list[dict[str, Any]]:
    combined = f"{text} {context}".strip()
    period = _period(combined)
    context_currency = _currency(combined)
    context_scale = _scale(combined)
    occupied_periods = _period_spans(text)
    values: list[dict[str, Any]] = []

    for match in _NUMBER.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied_periods):
            continue

        suffix = (match.group("suffix") or "").lower()
        displayed = match.group(0).strip()
        has_context = bool(
            match.group("currency")
            or suffix
            or context_currency
            or context_scale
            or "," in match.group("number")
            or "." in match.group("number")
            or (match.group("open") and match.group("close"))
        )
        if not has_context:
            continue

        raw_value = float(match.group("number").replace(",", ""))
        if match.group("open") and match.group("close"):
            raw_value = -raw_value

        value: dict[str, Any] = {"displayedValue": displayed, "value": raw_value}
        if suffix == "%":
            value["value"] = raw_value / 100
            value["unit"] = "%"
            value["scaleFactor"] = 0.01
        else:
            scale = SCALE_FACTORS.get(suffix) or context_scale
            currency = _currency(match.group("currency") or "") or context_currency
            if scale:
                value["value"] = raw_value * scale
                value["scaleFactor"] = scale
            if currency:
                value["currency"] = currency
        if period:
            value["period"] = period
        values.append(value)
    return values


def _table_context(cells: list[dict[str, Any]], cell: dict[str, Any], caption: str) -> str:
    row = int(cell["row"])
    column = int(cell["column"])
    above = sorted(
        (
            item
            for item in cells
            if int(item["column"]) == column and int(item["row"]) < row and item.get("text")
        ),
        key=lambda item: int(item["row"]),
        reverse=True,
    )
    left = sorted(
        (
            item
            for item in cells
            if int(item["row"]) == row and int(item["column"]) < column and item.get("text")
        ),
        key=lambda item: int(item["column"]),
        reverse=True,
    )
    parts = [str(item["text"]) for item in (*above[:2], *left[:2])]
    if caption:
        parts.append(caption)
    return " | ".join(parts)


def enrich_financial_numbers(document: dict[str, Any]) -> dict[str, Any]:
    """Populate v0.1 numeric metadata without replacing extracted text or cells."""

    for page in document.get("pages", ()):
        for block in page.get("blocks", ()):
            if block.get("type") == "text" and not block.get("numericValues"):
                values: list[dict[str, Any]] = []
                for line in str(block.get("text", "")).splitlines() or (str(block.get("text", "")),):
                    values.extend(_numbers(line))
                if values:
                    block["numericValues"] = values
            elif block.get("type") == "table":
                cells = list(block.get("cells", ()))
                caption = str(block.get("caption", ""))
                for cell in cells:
                    if cell.get("numericValue") or not str(cell.get("text", "")).strip():
                        continue
                    values = _numbers(
                        str(cell["text"]),
                        _table_context(cells, cell, caption),
                    )
                    if len(values) == 1:
                        cell["numericValue"] = values[0]
    return document
