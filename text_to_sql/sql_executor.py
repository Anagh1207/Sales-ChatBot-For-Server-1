"""
sql_executor.py — Executes a validated SQL string against the PostgreSQL
database using SQLAlchemy text() (read-only, parameterized wrapper).

Returns a dict with:
    columns: list[str]   — column names from the result set
    rows:    list[list]  — rows as lists of JSON-safe values
    row_count: int       — number of rows returned
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_ROWS = 200  # hard cap to prevent runaway result sets


def _json_safe(value: Any) -> Any:
    """Normalize DB driver types to JSON-serializable Python primitives."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return value
    if hasattr(value, "isoformat"):  # date / datetime
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def execute_sql(
    engine: Engine,
    db: Session,
    validated_sql: str,
) -> dict[str, Any]:
    """
    Execute `validated_sql` and return structured results.

    Args:
        engine:        SQLAlchemy engine (used for connection type hints only).
        db:            Active SQLAlchemy session.
        validated_sql: A safe, pre-validated SELECT string (no trailing ;).

    Returns:
        {"columns": [...], "rows": [[...], ...], "row_count": N,
         "truncated": bool}

    Raises:
        RuntimeError: if execution fails.
    """
    try:
        result = db.execute(text(validated_sql))
    except Exception as exc:
        logger.error("SQL execution failed: %s | SQL: %s", exc, validated_sql)
        raise RuntimeError(
            f"Query execution failed: {exc}. "
            "The model may have referenced a column that does not exist — "
            "try rephrasing your question."
        ) from exc

    columns: list[str] = list(result.keys())
    raw_rows = result.fetchmany(MAX_ROWS + 1)  # fetch one extra to detect truncation

    truncated = len(raw_rows) > MAX_ROWS
    rows_to_return = raw_rows[:MAX_ROWS]

    safe_rows = [
        [_json_safe(cell) for cell in row]
        for row in rows_to_return
    ]

    logger.info(
        "Executed SQL → %d columns, %d rows%s",
        len(columns),
        len(safe_rows),
        " (truncated)" if truncated else "",
    )

    return {
        "columns": columns,
        "rows": safe_rows,
        "row_count": len(safe_rows),
        "truncated": truncated,
    }
