"""
Regex and lightweight helpers to extract dates, years, quarters, and names.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

_YEAR = re.compile(r"\b(20[0-9]{2})\b")
_QUARTER_WORD = re.compile(r"\b(?:q|quarter)\s*([1-4])\b", re.I)
_QUARTER_THIS = re.compile(r"\bthis\s+quarter\b", re.I)
_YEAR_TILL = re.compile(
    r"(20[0-9]{2})\s*(?:till\s*date|to\s*date|year\s*to\s*date|ytd)\b", re.I
)
_TOP_N = re.compile(r"\btop\s+(\d+)\b", re.I)


def extract_year(text: str) -> int | None:
    m = _YEAR.search(text)
    return int(m.group(1)) if m else None


def extract_years(text: str) -> list[int]:
    return [int(y) for y in _YEAR.findall(text)]


def extract_quarter(text: str) -> int | None:
    m = _QUARTER_WORD.search(text)
    if m:
        return int(m.group(1))
    if _QUARTER_THIS.search(text):
        # Map "this quarter" using reference date (server today)
        today = date.today()
        return (today.month - 1) // 3 + 1
    return None


def extract_top_n(text: str, default: int = 5) -> int:
    m = _TOP_N.search(text)
    return int(m.group(1)) if m else default


def extract_date_range_keywords(text: str) -> dict[str, Any]:
    """Very small keyword map; returns start_date/end_date as ISO strings if detected."""
    lower = text.lower()
    today = date.today()
    start: date | None = None
    end: date | None = None

    if "till date" in lower or "to date" in lower or "ytd" in lower:
        m = _YEAR.search(text)
        if m:
            y = int(m.group(1))
            start = date(y, 1, 1)
            end = today if today.year == y else date(y, 12, 31)
    if "this year" in lower:
        start = date(today.year, 1, 1)
        end = today
    if "last year" in lower:
        y = today.year - 1
        start = date(y, 1, 1)
        end = date(y, 12, 31)

    out: dict[str, Any] = {}
    if start:
        out["start_date"] = start.isoformat()
    if end:
        out["end_date"] = end.isoformat()
    return out


def extract_customer_phrase(text: str) -> str | None:
    """
    Heuristic: capture text after 'for' / 'customer' before year or 'till'.
    """
    lower = text.lower()
    if "customer" in lower:
        m = re.search(r"customer\s+([A-Za-z0-9][A-Za-z0-9\s]{1,80})", text, re.I)
        if m:
            return m.group(1).strip()
    m = re.search(
        r"\bfor\s+([A-Za-z0-9][A-Za-z0-9\s]{1,80}?)(?=\s+(?:in|for|from|between|20\d{2}|till|to\s+date|ytd)|$)",
        text,
        re.I,
    )
    if m:
        cand = m.group(1).strip()
        # Trim trailing filler words
        cand = re.split(r"\b(?:in|from|between)\b", cand, maxsplit=1, flags=re.I)[0].strip()
        if len(cand) >= 2:
            return cand
    return None


def extract_salesperson_phrase(text: str) -> str | None:
    m = re.search(
        r"\b(?:salesperson|sales\s*person|rep)\s+([A-Za-z][A-Za-z\s'.-]{1,60})",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()
    return None
