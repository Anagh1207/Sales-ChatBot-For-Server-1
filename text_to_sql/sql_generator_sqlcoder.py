"""
sql_generator_sqlcoder.py — SQL generator tuned for defog/sqlcoder-70b-alpha.

SQLCoder was fine-tuned on a very specific prompt format that is different
from the general instruction-following format used in sql_generator.py.
Using the correct template is critical for good results.

Official SQLCoder prompt format (from defog/sqlcoder GitHub):

    ### Task
    Generate a SQL query to answer [QUESTION]{question}[/QUESTION]

    ### Database Schema
    The query will run on a database with the following schema:
    {create_table_ddl}

    ### Answer
    Given the database schema, here is the SQL query that
    [QUESTION]{question}[/QUESTION]
    [SQL]

SQLCoder then completes from [SQL] onward.

Available on OpenRouter as: defog/sqlcoder-70b-alpha
"""
from __future__ import annotations

import logging
import re

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. "
                "Add it to your .env file to use SQLCoder."
            )
        _client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
    return _client


def _build_sqlcoder_prompt(ddl_schema: str, user_question: str) -> str:
    """
    Build the prompt format optimized for Qwen Coder 32B while preserving the DDL structure.
    """
    return (
        "You are an expert PostgreSQL query writer. Use the following database schema to answer the user's question.\n\n"
        "### DATABASE SCHEMA:\n"
        f"{ddl_schema}\n\n"
        "### USER QUESTION:\n"
        f"{user_question}\n\n"
        "### CRITICAL INSTRUCTIONS:\n"
        "- Generate a single, complete, valid PostgreSQL SELECT query that directly answers the question.\n"
        "- ONLY select columns that are relevant to answering the question. Do NOT select extra columns (like sales_person, country, job_type, product_type) unless explicitly asked to break down or filter by them.\n"
        "- Make sure the query is syntactically complete. Do not leave any brackets, quotes, or clauses unfinished.\n"
        "- If you use a literal string date inside date functions like EXTRACT() or date_trunc(), you MUST explicitly cast it, for example: CAST('2026-05-22' AS DATE) or '2026-05-22'::DATE.\n"
        "- **Financial Year (FY)** runs from **July 1st of a year to June 30th of the next year**. To group or filter by financial year, use the formula: `EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month'))`. This returns the starting year Y of the financial year (e.g. `2024` represents the financial year starting 2024-07-01 and ending 2025-06-30, which should be displayed as '2024/25' or 'FY2024'). Today is '2026-05-22' (FY 2025/26 starting year 2025). The prior financial year is FY 2024/25 (starting year 2024).\n"
        "- For exclusion filtering (e.g. finding customers who stopped buying), NEVER use a raw NOT IN subquery without an IS NOT NULL filter, as a single NULL value inside the NOT IN list results in 0 rows. Use NOT EXISTS or add an explicit IS NOT NULL check in the subquery.\n"
        "- Output ONLY the SQL query inside a markdown code block (e.g. ```sql ... ```). No conversational text, pleasantries, or explanations."
    )


def _extract_limit_from_question(question: str) -> int:
    """
    Parse a number from phrases like "top 5", "bottom 3", "first 10",
    "last 20", "show me 7", etc.  Returns the first integer found that
    is plausibly a row-count limit, or 10 as a safe default.
    """
    # Match: top/bottom/first/last/show/give + optional 'me' + number
    m = re.search(
        r"\b(?:top|bottom|first|last|show\s+me|give\s+me|limit)?\s*(\d+)",
        question,
        re.I,
    )
    if m:
        n = int(m.group(1))
        # Sanity check — ignore years like 2024, 2025
        if 1 <= n <= 10_000:
            return n
    return 10  # safe default


def _clean_sqlcoder_output(raw: str, user_question: str = "") -> str:
    """
    SQLCoder often outputs only the SQL body (no SELECT keyword at start
    if it was in the completion). Strip [SQL]/[/SQL] tags if present,
    and common markdown fences.

    Also repairs a truncated bare LIMIT clause that occurs when max_tokens
    cuts the output before the model could write the number.  The limit
    value is recovered from the user's original question so that
    "top 5 customers" correctly produces LIMIT 5, not a blocked query.
    """
    # Remove [SQL] / [/SQL] tags
    raw = re.sub(r"\[/?SQL\]", "", raw, flags=re.I).strip()
    # Remove markdown fences
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.I | re.M)
    raw = re.sub(r"\s*```$", "", raw, flags=re.M)
    raw = raw.strip()

    # ── Repair bare LIMIT (truncated by max_tokens) ────────────────────────
    # Pattern: LIMIT at end of string with no following digit
    if re.search(r"\bLIMIT\s*$", raw, flags=re.I):
        limit_n = _extract_limit_from_question(user_question)
        logger.warning(
            "SQLCoder output has bare LIMIT (truncated) — "
            "completing with LIMIT %d from question %r",
            limit_n, user_question[:60],
        )
        raw = re.sub(r"\bLIMIT\s*$", f"LIMIT {limit_n}", raw, flags=re.I)

    return raw


def generate_sql_sqlcoder(
    ddl_schema: str,
    user_message: str,
    model: str | None = None,
) -> str:
    """
    Call Qwen Coder to generate a SQL query using the DDL schema context.

    Args:
        ddl_schema:   CREATE TABLE DDL string from build_ddl_schema().
        user_message: Natural language question from the user.
        model:        Override model ID; defaults to settings.sqlcoder_model.

    Returns:
        A raw SQL string (needs validation before execution).

    Raises:
        RuntimeError: on API failure.
    """
    client = _get_client()
    chosen_model = model or settings.sqlcoder_model

    prompt = _build_sqlcoder_prompt(ddl_schema, user_message)

    logger.info("Requesting SQL from SQLCoder: %s", chosen_model)

    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert PostgreSQL developer. "
                        "Given a table schema, you generate a single, complete, valid PostgreSQL SELECT query. "
                        "Do not include conversational text, pleasantries, or explanations in your output."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,   # deterministic for SQL
            max_tokens=1024,
        )
    except Exception as exc:
        logger.error("SQLCoder generation failed: %s", exc)
        raise RuntimeError(f"SQLCoder API call failed: {exc}") from exc

    raw = (resp.choices[0].message.content or "").strip()

    # Robust parsing: Extract SQL code block anywhere in the output first.
    code_block_match = re.search(r"```(?:sql)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if code_block_match:
        raw = code_block_match.group(1).strip()
    else:
        # Fallback: Find the first SQL statement starting with SELECT or WITH and ending with a semicolon.
        sql_match = re.search(r"\b(SELECT|WITH)\b.*?;", raw, flags=re.DOTALL | re.IGNORECASE)
        if sql_match:
            raw = sql_match.group(0).strip()
        else:
            # If no semicolon was generated but it has SELECT/WITH, grab from SELECT/WITH to the end.
            sql_match_nosemi = re.search(r"\b(SELECT|WITH)\b.*", raw, flags=re.DOTALL | re.IGNORECASE)
            if sql_match_nosemi:
                raw = sql_match_nosemi.group(0).strip()

    # Pass the original question so bare LIMIT can be completed correctly
    cleaned = _clean_sqlcoder_output(raw, user_question=user_message)

    if not cleaned:
        raise RuntimeError("SQLCoder returned an empty response.")

    logger.debug("SQLCoder generated SQL: %s", cleaned)
    return cleaned
