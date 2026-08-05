"""Deterministic enrichment of raw extraction into finance-aware canonical facts."""

from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from financial_slides_worker.extraction.models import CanonicalDocument

_NUMBER = re.compile(
    r"(?P<open>\()?\s*(?P<currency>USD|SAR|EUR|GBP|AED|\$|€|£)?\s*"
    r"(?P<number>[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*"
    r"(?P<scale>bn|billions?|mm|millions?|mn|m|thousands?|k)?\s*"
    r"(?P<percent>%|percent|percentage points?|bps)?\s*(?P<close>\))?\s*"
    r"(?P<footnote>[*†‡]+|\[\d+\])?",
    re.IGNORECASE,
)
_PERIODS = (
    re.compile(r"\bQ(?P<quarter>[1-4])\s*(?P<year>20\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(?P<year>20\d{2})\s*Q(?P<quarter>[1-4])\b", re.IGNORECASE),
    re.compile(r"\bFY\s*(?P<year>20\d{2})\b", re.IGNORECASE),
)
_CURRENCY_CODES = {"$": "USD", "€": "EUR", "£": "GBP"}
_SCALE_FACTORS = {
    "k": 1_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "bn": 1_000_000_000,
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
}
_FIELD_NAMES = (
    "label",
    "metric",
    "statementType",
    "displayedValue",
    "parsedValue",
    "normalizedValue",
    "unit",
    "currency",
    "scaleFactor",
    "period",
    "scope",
    "scenario",
    "restatementStatus",
    "evidence",
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug and slug[0].isdigit():
        slug = f"metric-{slug}"
    return slug or "unclassified-metric"


def _metric_name(label: str) -> str:
    without_unit = re.sub(
        r"\s*\((?=[^)]*(?:USD|SAR|EUR|GBP|AED|%|million|billion|thousand))[^)]*\)\s*$",
        "",
        label,
        flags=re.IGNORECASE,
    ).strip()
    return without_unit or label.strip() or "Unclassified metric"


def _period(value: str) -> dict[str, Any]:
    for pattern in _PERIODS:
        match = pattern.search(value)
        if not match:
            continue
        year = int(match.group("year"))
        quarter = match.groupdict().get("quarter")
        if quarter:
            quarter_number = int(quarter)
            start_month = (quarter_number - 1) * 3 + 1
            end_month = start_month + 2
            return {
                "type": "quarter",
                "label": match.group(0).strip(),
                "startDate": date(year, start_month, 1).isoformat(),
                "endDate": date(year, end_month, monthrange(year, end_month)[1]).isoformat(),
            }
        return {
            "type": "year",
            "label": match.group(0).strip(),
            "startDate": date(year, 1, 1).isoformat(),
            "endDate": date(year, 12, 31).isoformat(),
        }

    year_match = re.fullmatch(r"\s*(20\d{2})\s*", value)
    if year_match:
        year = int(year_match.group(1))
        return {
            "type": "year",
            "label": year_match.group(0).strip(),
            "startDate": date(year, 1, 1).isoformat(),
            "endDate": date(year, 12, 31).isoformat(),
        }
    return {"type": "unknown", "label": None, "startDate": None, "endDate": None}


def _context_value(context: str, options: tuple[str, ...], default: str) -> str:
    lowered = context.lower()
    return next((option for option in options if option.replace("_", " ") in lowered), default)


def _statement_type(context: str) -> str:
    matches = (
        (("income statement", "statement of operations", "profit and loss"), "income_statement"),
        (("balance sheet", "financial position"), "balance_sheet"),
        (("cash flow", "cash-flow"), "cash_flow"),
        (("segment",), "segment"),
        (("kpi", "key performance indicator"), "kpi"),
    )
    lowered = context.lower()
    for terms, result in matches:
        if any(term in lowered for term in terms):
            return result
    return "unknown"


def _number(value: str, context: str) -> dict[str, Any] | None:
    match = _NUMBER.fullmatch(value.strip())
    if not match:
        return None
    try:
        parsed = Decimal(match.group("number").replace(",", ""))
    except InvalidOperation:
        return None
    if match.group("open") and match.group("close"):
        parsed = -abs(parsed)

    combined = f"{value} {context}".lower()
    percent = (match.group("percent") or "").lower()
    currency_token = match.group("currency")
    currency = None
    if currency_token:
        currency = _CURRENCY_CODES.get(currency_token, currency_token.upper())
    if currency is None:
        currency_match = re.search(r"\b(USD|SAR|EUR|GBP|AED)\b", combined, re.IGNORECASE)
        if currency_match:
            currency = currency_match.group(1).upper()

    scale_token = (match.group("scale") or "").lower()
    scale_factor = _SCALE_FACTORS.get(scale_token)
    if scale_factor is None:
        scale_match = re.search(
            r"\b(bn|billions?|mm|millions?|mn|thousands?)\b", combined, re.IGNORECASE
        )
        scale_factor = _SCALE_FACTORS.get(scale_match.group(1).lower(), 1) if scale_match else 1

    if percent.startswith("bp"):
        unit = "basis_points"
        scale_factor = Decimal("0.0001")
    elif percent:
        unit = "percentage"
        scale_factor = Decimal("0.01")
    elif currency:
        unit = "currency"
        scale_factor = Decimal(scale_factor)
    else:
        unit = _context_value(combined, ("ratio", "count"), "count")
        scale_factor = Decimal(scale_factor)

    normalized = parsed * scale_factor
    return {
        "parsedValue": float(parsed),
        "normalizedValue": float(normalized),
        "unit": unit,
        "currency": currency,
        "scaleFactor": float(scale_factor),
    }


def _warning(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _cell_map(block: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    return {(cell["row"], cell["column"]): cell for cell in block.get("cells", [])}


def _header_path(
    block: dict[str, Any],
    cells: dict[tuple[int, int], dict[str, Any]],
    row: int,
    column: int,
) -> list[str]:
    path = [*block.get("source", {}).get("sectionPath", [])]
    if block.get("caption"):
        path.append(block["caption"])

    for candidate in block.get("cells", []):
        text = str(candidate.get("text", "")).strip()
        if not text:
            continue
        covers_column = (
            candidate["column"] <= column < (candidate["column"] + candidate.get("columnSpan", 1))
        )
        if candidate["row"] < row and covers_column:
            path.append(text)

    for candidate_column in range(column):
        text = str(cells.get((row, candidate_column), {}).get("text", "")).strip()
        if text:
            path.append(text)
    return list(dict.fromkeys(path))


def _fact(
    *,
    page: dict[str, Any],
    block: dict[str, Any],
    displayed_value: str,
    label: str,
    header_path: list[str],
    cell: dict[str, Any] | None,
    ordinal: int,
    context_hint: str = "",
) -> dict[str, Any]:
    context = " | ".join([*header_path, label, displayed_value, context_hint])
    parsed = _number(displayed_value, context)
    warnings: list[dict[str, str]] = []
    if cell is not None and not label.strip():
        warnings.append(
            _warning(
                "header.mapping_broken",
                "The table value could not be associated with a row or column header.",
            )
        )
    if parsed is None:
        parsed = {
            "parsedValue": None,
            "normalizedValue": None,
            "unit": None,
            "currency": None,
            "scaleFactor": None,
        }
        warnings.append(
            _warning("numeric.parse_failed", "The displayed value could not be parsed.")
        )

    period = _period(context)
    if period["type"] == "unknown":
        warnings.append(_warning("period.missing", "No reporting period could be assigned safely."))
    if parsed["unit"] is None:
        warnings.append(_warning("unit.missing", "No unit could be assigned safely."))
    if parsed["unit"] == "currency" and parsed["currency"] is None:
        warnings.append(_warning("currency.missing", "A currency amount has no currency code."))

    base_confidence = float(
        cell.get("confidence", block["confidence"]) if cell else block["confidence"]
    )
    confidence = {field: round(base_confidence, 4) for field in _FIELD_NAMES}
    for ambiguous in ("statementType", "period", "scope", "scenario", "restatementStatus"):
        confidence[ambiguous] = round(base_confidence * 0.8, 4)
    if period["type"] == "unknown":
        confidence["period"] = 0.0
    if parsed["unit"] is None:
        confidence["unit"] = 0.0
    if parsed["parsedValue"] is None:
        confidence["parsedValue"] = 0.0
        confidence["normalizedValue"] = 0.0
        confidence["scaleFactor"] = 0.0

    source = cell.get("source", block["source"]) if cell else block["source"]
    evidence: dict[str, Any] = {
        "sourceId": source["sourceId"],
        "pageNumber": page["pageNumber"],
        "blockId": block["id"],
        "headerPath": header_path,
    }
    if source.get("boundingBox"):
        evidence["boundingBox"] = source["boundingBox"]
    if cell is not None:
        evidence.update({"tableId": block["id"], "row": cell["row"], "column": cell["column"]})

    scenario = _context_value(context, ("actual", "budget", "forecast"), "unknown")
    restatement = _context_value(context, ("restated", "originally_reported"), "not_indicated")
    entity_match = re.search(r"\b(?:entity|company):\s*([^|]+)", context, re.IGNORECASE)
    segment_match = re.search(r"\bsegment:\s*([^|]+)", context, re.IGNORECASE)
    displayed_label = label.strip() or "Unclassified metric"
    metric_name = _metric_name(displayed_label)
    return {
        "id": f"fact-{page['pageNumber']}-{_slug(block['id'])}-{ordinal}",
        "label": displayed_label,
        "metric": {"id": _slug(metric_name), "name": metric_name},
        "statementType": _statement_type(context),
        "displayedValue": displayed_value,
        **parsed,
        "period": period,
        "scope": {
            "entity": entity_match.group(1).strip() if entity_match else None,
            "segment": segment_match.group(1).strip() if segment_match else None,
        },
        "scenario": scenario,
        "restatementStatus": restatement,
        "evidence": evidence,
        "confidence": {"overall": round(min(confidence.values()), 4), **confidence},
        "warnings": warnings,
        "relations": {"duplicateOf": [], "conflictsWith": []},
    }


def _table_facts(page: dict[str, Any], block: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    cells = _cell_map(block)
    for cell in sorted(block.get("cells", []), key=lambda item: (item["row"], item["column"])):
        displayed = str(cell.get("text", "")).strip()
        if cell["row"] == 0 or cell["column"] == 0 or not displayed:
            continue
        if _number(displayed, "") is None and (
            _period(displayed)["type"] != "unknown"
            or (
                not any(character.isdigit() for character in displayed)
                and displayed not in {"-", "–", "—"}
            )
        ):
            continue
        path = _header_path(block, cells, cell["row"], cell["column"])
        row_label = str(cells.get((cell["row"], 0), {}).get("text", "")).strip()
        column_label = str(cells.get((0, cell["column"]), {}).get("text", "")).strip()
        if _period(row_label)["type"] != "unknown":
            label = column_label
        elif _period(column_label)["type"] != "unknown":
            label = row_label
        else:
            label = row_label or column_label
        facts.append(
            _fact(
                page=page,
                block=block,
                displayed_value=displayed,
                label=label,
                header_path=path,
                cell=cell,
                ordinal=len(facts) + 1,
            )
        )
    return facts


def _text_facts(page: dict[str, Any], block: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(block.get("text", ""))
    facts = []
    last_label = "Unclassified metric"
    for line in text.splitlines() or [text]:
        period_spans = [match.span() for pattern in _PERIODS for match in pattern.finditer(line)]
        value_matches = [
            match
            for match in _NUMBER.finditer(line)
            if not any(match.start() < end and match.end() > start for start, end in period_spans)
        ]
        if not value_matches and line.strip() and _period(line)["type"] == "unknown":
            last_label = line.strip(" :-–—,.;|")[-120:]
            continue
        for match in value_matches:
            displayed = match.group(0).strip()
            if not displayed:
                continue
            prefix = line[: match.start()].strip(" :-–—,.;|")
            for pattern in _PERIODS:
                prefix = pattern.sub("", prefix).strip(" :-–—,.;|")
            label = prefix[-120:] if prefix else last_label
            path = [*block.get("source", {}).get("sectionPath", []), label]
            facts.append(
                _fact(
                    page=page,
                    block=block,
                    displayed_value=displayed,
                    label=label,
                    header_path=list(dict.fromkeys(path)),
                    cell=None,
                    ordinal=len(facts) + 1,
                    context_hint=line,
                )
            )
    return facts


def _link_duplicates(facts: list[dict[str, Any]], findings: list[dict[str, Any]]) -> None:
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for fact in facts:
        key = (
            fact["metric"]["id"],
            fact["period"]["label"],
            fact["scope"]["entity"],
            fact["scope"]["segment"],
            fact["scenario"],
        )
        prior = seen.get(key)
        if prior is None:
            seen[key] = fact
            continue
        unit_identity = (fact["unit"], fact["currency"], fact["scaleFactor"])
        prior_unit_identity = (prior["unit"], prior["currency"], prior["scaleFactor"])
        if unit_identity != prior_unit_identity:
            prior["relations"]["conflictsWith"].append(fact["id"])
            fact["relations"]["conflictsWith"].append(prior["id"])
            findings.append(
                {
                    "code": "unit.conflict",
                    "severity": "error",
                    "message": "Conflicting units were preserved for the same canonical identity.",
                    "factIds": [prior["id"], fact["id"]],
                }
            )
        elif prior["normalizedValue"] == fact["normalizedValue"]:
            fact["relations"]["duplicateOf"].append(prior["id"])
            findings.append(
                {
                    "code": "fact.duplicate",
                    "severity": "warning",
                    "message": "The same canonical fact appears more than once.",
                    "factIds": [prior["id"], fact["id"]],
                }
            )
        else:
            prior["relations"]["conflictsWith"].append(fact["id"])
            fact["relations"]["conflictsWith"].append(prior["id"])
            findings.append(
                {
                    "code": "fact.conflict",
                    "severity": "error",
                    "message": "Conflicting values were preserved for the same canonical identity.",
                    "factIds": [prior["id"], fact["id"]],
                }
            )


def _reconcile_totals(facts: list[dict[str, Any]], findings: list[dict[str, Any]]) -> None:
    by_table_column: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for fact in facts:
        evidence = fact["evidence"]
        if "tableId" in evidence and fact["normalizedValue"] is not None:
            by_table_column.setdefault((evidence["tableId"], evidence["column"]), []).append(fact)

    for grouped in by_table_column.values():
        subtotal: list[dict[str, Any]] = []
        for fact in sorted(grouped, key=lambda item: item["evidence"]["row"]):
            if re.search(r"\btotal\b", fact["label"], re.IGNORECASE):
                unit_identity = (fact["unit"], fact["currency"], fact["scaleFactor"])
                if subtotal and any(
                    (item["unit"], item["currency"], item["scaleFactor"]) != unit_identity
                    for item in subtotal
                ):
                    findings.append(
                        {
                            "code": "unit.conflict",
                            "severity": "error",
                            "message": "A total and its preceding values use conflicting units.",
                            "factIds": [*(item["id"] for item in subtotal), fact["id"]],
                        }
                    )
                    subtotal = []
                    continue
                expected = sum(item["normalizedValue"] for item in subtotal)
                if subtotal and abs(expected - fact["normalizedValue"]) > max(
                    0.01, abs(expected) * 1e-9
                ):
                    findings.append(
                        {
                            "code": "total.unreconciled",
                            "severity": "warning",
                            "message": "An extracted total does not reconcile with the preceding values.",
                            "factIds": [*(item["id"] for item in subtotal), fact["id"]],
                        }
                    )
                subtotal = []
            else:
                subtotal.append(fact)


def enrich_financial_facts(document: CanonicalDocument) -> CanonicalDocument:
    """Return Extracted Document v0.2 without modifying the provider's raw blocks."""

    enriched = deepcopy(document)
    facts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for page in enriched.get("pages", []):
        for block in page.get("blocks", []):
            if block.get("type") == "table":
                facts.extend(_table_facts(page, block))
            elif block.get("type") == "text":
                facts.extend(_text_facts(page, block))

    for fact in facts:
        for warning in fact["warnings"]:
            findings.append(
                {
                    "code": warning["code"],
                    "severity": warning["severity"],
                    "message": warning["message"],
                    "factIds": [fact["id"]],
                }
            )
    _link_duplicates(facts, findings)
    _reconcile_totals(facts, findings)

    enriched["schemaVersion"] = "0.2"
    enriched["financialFacts"] = facts
    enriched["factValidation"] = findings
    return enriched
