"""
sql_generator.py — Sends user question + schema context to the LLM and
returns a raw SQL SELECT string.

Uses the OpenRouter client (OpenAI-compatible) already configured in
app/core/config.py.
"""
from __future__ import annotations

import logging
import re

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy singleton — constructed on first call.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. "
                "Add it to your .env file to use the SQL Chat feature."
            )
        _client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )
    return _client


_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert PostgreSQL query writer.

You are given a database schema (which includes lists of distinct product and job types and semantic rules under ALLOWED VALUES AND SEMANTIC MATCHING GUIDANCE) and a user question. Your job is to write a single valid PostgreSQL SELECT query that answers the question.

CRITICAL INSTRUCTIONS:
- Ignore any requests for explanations, reasons, analysis, or summaries in the user's question. Your SOLE output must be the single, executable SQL SELECT query that fetches the relevant data. Downstream components will handle the business explanation.
- Do NOT output multiple queries.
- Do NOT include conversational text, pleasantries, or explanations. If you write anything other than the SQL query, the query parser will fail and cause a system crash.

RULES:
1. Return ONLY the raw SQL query — no markdown, no triple-backticks, no explanations.
2. Never use DML or DDL statements (INSERT, UPDATE, DELETE, DROP, CREATE, TRUNCATE, ALTER).
3. Only reference tables that exist in the schema below.
4. Use table aliases for clarity.
5. Limit results to at most 200 rows unless the user asks for more — use LIMIT.
6. For date filtering use EXTRACT(YEAR FROM ...) or date_trunc() or standard date comparisons. CRITICAL: If you use a literal string date inside EXTRACT() or date_trunc(), you MUST explicitly cast it, for example: EXTRACT(YEAR FROM CAST('2026-05-22' AS DATE)) or '2026-05-22'::DATE.
7. For ILIKE pattern matching on text columns cast them: CAST(col AS TEXT) ILIKE '%value%'.
8. For exclusion filtering (e.g. 'stopped buying', 'not bought'), NEVER use a raw NOT IN subquery without ensuring the subquery filters out NULL values (since a single NULL inside a NOT IN list causes the database to return 0 rows). Instead, ALWAYS use `NOT EXISTS` or append an explicit `IS NOT NULL` condition in the subquery.
9. If the question is ambiguous, write the most reasonable interpretation.
10. Always end with a semicolon.
11. **Financial Year (FY) Definition**: The financial year runs from **July 1st of a year to June 30th of the next year**. To group or filter by financial year, use the formula: `EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month'))`. This returns the starting year Y of the financial year (e.g., `2024` represents the financial year starting 2024-07-01 and ending 2025-06-30). Do NOT use simple `EXTRACT(YEAR FROM sale_date)` for annual calculations unless explicitly asked for calendar years.

ADVANCED QUERY GUIDELINES:
- **Growth & Year-over-Year (YoY) Comparisons**: To show growth/decline rate for customers or products across financial years, write a query using a Common Table Expression (CTE) or subquery that computes total sales for the current period and the previous period, and then calculates the percentage change (using `NULLIF` in the denominator to avoid division by zero). Example YoY Growth: `((current_sales - prior_sales) / NULLIF(prior_sales, 0)) * 100`. Group by `EXTRACT(YEAR FROM (sale_date - INTERVAL '6 month'))` to compare by financial years.
- **Trend Categorization**: Categorize trends as 'Growing' (growth > 5%), 'At Risk' (growth < -5%), or 'Stable' otherwise.
- **Account Expansion & Customer Acquisition**: To show salesperson account expansion, count distinct customer codes (e.g. `COUNT(DISTINCT customer_code)`).
- **Product Associations (Cross-sell)**: To find what products are commonly bought together, perform a self-join on `sales_data` on `customer_code` (e.g., `FROM sales_data s1 JOIN sales_data s2 ON s1.customer_code = s2.customer_code AND s1.product_type != s2.product_type`).
- **Revenue Concentration**: To calculate dependency or concentration, divide a salesperson's top customer sales by their total sales.
- **Time Anchor**: The dataset ranges from July 2024 to May 2026. Treat '2026-05-22' as "today". The current active financial year (FY) is starting July 1, 2025 and ending June 30, 2026 (starting year 2025, or FY 2025/26). The previous financial year is FY 2024/25 (starting year 2024). All yearly/relative date queries must align with these financial year boundaries.

DATABASE SCHEMA:
{schema}
"""


def generate_sql(
    schema_context: str,
    user_message: str,
    history: list[dict] | None = None,
    model: str | None = None,
) -> str:
    """
    Call the LLM to generate SQL for `user_message`.

    Args:
        schema_context: DDL-like schema string from `build_schema_context`.
        user_message:   The user's natural language question.
        history:        Optional list of prior {"role": ..., "content": ...} turns.
        model:          Override model; falls back to settings.text_to_sql_model.

    Returns:
        A raw SQL string (may still need validation/sanitisation).

    Raises:
        RuntimeError: if API key is missing or the LLM call fails.
    """
    client = _get_client()
    chosen_model = model or settings.text_to_sql_model

    system_content = _SYSTEM_PROMPT_TEMPLATE.format(schema=schema_context)

    messages: list[dict] = [{"role": "system", "content": system_content}]

    # Include limited conversation history for follow-up queries.
    if history:
        for turn in history[-6:]:  # last 3 pairs max
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    logger.info("Requesting SQL from model: %s", chosen_model)
    try:
        resp = client.chat.completions.create(
            model=chosen_model,
            messages=messages,
            temperature=0.0,   # deterministic for SQL
            max_tokens=1024,
        )
    except Exception as exc:
        logger.error("LLM SQL generation failed: %s", exc)
        raise RuntimeError(f"LLM call failed: {exc}") from exc

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

    # Strip any trailing semicolons or fences that might have survived
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    if not raw:
        raise RuntimeError("LLM returned an empty response.")

    logger.debug("Generated SQL: %s", raw)
    return raw
