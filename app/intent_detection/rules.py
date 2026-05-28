"""
Rule-based intent classification for business analytics queries.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.intent_detection.entities import (
    extract_customer_phrase,
    extract_date_range_keywords,
    extract_quarter,
    extract_salesperson_phrase,
    extract_top_n,
    extract_year,
    extract_years,
)


@dataclass
class IntentResult:
    intent: str
    confidence: float
    parameters: dict[str, Any] = field(default_factory=dict)
    needs_clarification: bool = False
    clarification_question: str | None = None


def _has_any(text: str, words: list[str]) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def _is_chitchat(lower: str) -> bool:
    """Greetings / thanks — not analytics (avoid matching stale keywords from other turns)."""
    # Whole-message patterns only (short utterances).
    if len(lower) > 120:
        return False
    return bool(
        re.match(
            r"^\s*(hi|hello|hey|yo|sup|hiya|good\s+(morning|afternoon|evening)|"
            r"thanks?(\s+you)?|thx|ty|bye|goodbye|ok|okay|cool)\s*[!?.]*\s*$",
            lower,
        )
    )


def classify_intent(message: str) -> IntentResult:
    """
    Keyword + regex driven intent detection.
    Order matters: more specific patterns first.

    IMPORTANT: Pass only the *current* user utterance here. Do not concatenate chat
    history — older messages contain words like "top customer" and would wrongly win
    over later messages such as "hi".
    """
    text = message.strip()
    # Common typo: "this quater"
    text = re.sub(r"\bquater\b", "quarter", text, flags=re.I)
    lower = text.lower()
    params: dict[str, Any] = {}

    if _is_chitchat(lower):
        return IntentResult("chitchat", 1.0, {})

    # Target / quota analytics (check negations before positive "meet" phrases)
    if _has_any(lower, ["target", "quota", "achievement"]):
        params["year"] = extract_year(text)
        params["quarter"] = extract_quarter(text)
        params.update(extract_date_range_keywords(text))
        if "did not" in lower or "didn't" in lower or "not meet" in lower:
            params["not_met_only"] = True
        elif (
            "met target" in lower
            or "meet target" in lower
            or re.search(r"\bwho\s+met\b", lower)
        ):
            params["met_only"] = True
        return IntentResult("target_achievement", 0.84, params)

    # Top customers (include patterns like "top 5 customers this quarter")
    if (
        _has_any(lower, ["top customer", "top customers", "biggest customer", "largest customer"])
        or ("top" in lower and "customer" in lower)
    ):
        # "Who was the top customer?" → limit 1; "top 5 customers" → explicit or plural default 5
        if re.search(r"\bcustomers\b", lower):
            params["limit"] = extract_top_n(text, 5)
        else:
            params["limit"] = extract_top_n(text, 1)
        params["year"] = extract_year(text)
        params["quarter"] = extract_quarter(text)
        params.update(extract_date_range_keywords(text))
        return IntentResult("top_customers", 0.88, params)

    # Sales by salesperson / performance
    if _has_any(
        lower,
        [
            "by salesperson",
            "by sales person",
            "per salesperson",
            "sales by rep",
            "each salesperson",
            "salesperson performance",
        ],
    ):
        params["year"] = extract_year(text)
        params["quarter"] = extract_quarter(text)
        params.update(extract_date_range_keywords(text))
        return IntentResult("salesperson_performance", 0.86, params)

    # Quarterly sales explicit
    if "quarter" in lower or re.search(r"\bq[1-4]\b", lower):
        params["year"] = extract_year(text)
        params["quarter"] = extract_quarter(text)
        if params["year"] is None:
            ys = extract_years(text)
            if ys:
                params["year"] = ys[0]
        params.update(extract_date_range_keywords(text))
        return IntentResult("quarterly_sales", 0.8, params)

    # Yearly / total this year
    if _has_any(lower, ["total sales", "sales this year", "yearly sales", "annual sales", "full year"]):
        params["year"] = extract_year(text)
        params.update(extract_date_range_keywords(text))
        return IntentResult("yearly_sales", 0.82, params)

    # Generic sales summary (customer / job / filters)
    if _has_any(lower, ["sales", "revenue", "turnover", "contract", "invoice"]):
        params["customer"] = extract_customer_phrase(text)
        params["salesperson"] = extract_salesperson_phrase(text)
        params["year"] = extract_year(text)
        params.update(extract_date_range_keywords(text))
        params["quarter"] = extract_quarter(text)

        # Clarification: customer mentioned but no time window
        if params.get("customer") and not any(
            [
                params.get("year"),
                params.get("start_date"),
                params.get("end_date"),
                params.get("quarter"),
            ]
        ):
            if re.search(r"\b(all|every)\s+years?\b", lower) or "all time" in lower:
                return IntentResult("sales_summary", 0.8, params)
            return IntentResult(
                "sales_summary",
                0.75,
                params,
                needs_clarification=True,
                clarification_question="Do you want all years or a specific year (for example 2025 till date)?",
            )

        return IntentResult("sales_summary", 0.78, params)

    # Fallback: treat as sales summary with whole message as loose customer filter attempt
    params["year"] = extract_year(text)
    params.update(extract_date_range_keywords(text))
    return IntentResult("sales_summary", 0.35, params)
