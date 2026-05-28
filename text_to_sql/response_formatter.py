"""
response_formatter.py — Generates a natural-language summary of the SQL
query results using the LLM.

Falls back to a generic template if the LLM call fails so the pipeline
never breaks due to a formatting error.
"""
from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI | None:
    global _client
    if not settings.openrouter_api_key:
        return None
    if _client is None:
        _client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
    return _client


_MAX_ROWS_FOR_SUMMARY = 20  # Only send a preview to the LLM to keep tokens low.


def _build_text_preview(
    user_question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
    truncated: bool,
) -> str:
    """Format a compact preview of results for the LLM to summarize."""
    header = " | ".join(columns)
    separator = "-" * len(header)
    row_lines = [
        " | ".join(str(cell) if cell is not None else "NULL" for cell in row)
        for row in rows[:_MAX_ROWS_FOR_SUMMARY]
    ]
    table_str = "\n".join([header, separator] + row_lines)
    trunc_note = f"\n(Results truncated — showing first {_MAX_ROWS_FOR_SUMMARY} of {len(rows)} rows)" if truncated else ""
    return (
        f"User question: {user_question}\n"
        f"SQL executed:\n{sql}\n\n"
        f"Results ({len(rows)} row(s)){trunc_note}:\n{table_str}"
    )


def generate_summary(
    user_question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
    truncated: bool = False,
    model: str | None = None,
) -> str:
    """
    Ask the LLM to write a concise, human-readable summary of the results.

    Returns:
        A plain-text summary string. Falls back to a template on failure.
    """
    client = _get_client()
    if client is None:
        return _fallback_summary(columns, rows, truncated)

    chosen_model = model or settings.text_to_sql_model

    if not rows:
        return "The query returned no results for your question."

    preview = _build_text_preview(user_question, sql, columns, rows, truncated)

    system = (
        "You are a highly skilled commercial business analyst.\n"
        "Your task is to write a comprehensive, data-driven summary and deep reasoning "
        "that directly answers the user's question using the provided SQL results.\n\n"
        "GUIDELINES:\n"
        "1. Highlight key figures (growth rates, total sales, top customers, salespeople performance).\n"
        "2. CRITICAL CURRENCY & FORMATTING RULES: All monetary sales/revenue figures must be formatted with the 'EDP' currency symbol (e.g. 'EDP 100,000'). All final displayed revenue figures must be ROUNDED OFF to the nearest whole integer (no decimals allowed in the final displayed monetary amounts, e.g. show 'EDP 500,240' instead of 'EDP 500,240.50').\n"
        "3. Keep in mind the company's Financial Year runs from July 1st of a year to June 30th of the next year (e.g., FY 2024/25, FY 2025/26). Reflect this calendar in your annual comparisons and summaries.\n"
        "4. Provide commercial reasoning and insights. If the data shows growing or declining accounts, "
        "   products, or sectors, explain the implications (e.g., churn risk, territory optimization, cross-selling potential).\n"
        "5. Use professional, clear markdown formatting (bolding, lists, and spacing) to make the reasoning easy to read.\n"
        "6. Do not repeat the raw SQL query. Focus entirely on the business meaning and logical reasoning.\n"
        "7. Be concise but extremely insightful, ensuring the user gets both the data summary and the underlying business 'why'."
    )

    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": preview},
            ],
            temperature=0.3,
            max_tokens=800,
        )
        summary = (resp.choices[0].message.content or "").strip()
        return summary or _fallback_summary(columns, rows, truncated)
    except Exception as exc:
        logger.warning("Summary generation failed: %s", exc)
        return _fallback_summary(columns, rows, truncated)


def _fallback_summary(
    columns: list[str],
    rows: list[list[Any]],
    truncated: bool,
) -> str:
    """Generic summary when LLM is unavailable."""
    if not rows:
        return "The query returned no results."
    count = len(rows)
    trunc = f" (first {count} shown)" if truncated else ""
    return f"Found {count} result(s){trunc}. See the table below for details."
