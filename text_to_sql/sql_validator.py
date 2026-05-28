"""
sql_validator.py — Safety layer between LLM output and the database.

Uses sqlglot (pure-Python SQL parser) to:
  1. Ensure the statement is a SELECT (no DML/DDL).
  2. Verify only allowed tables are referenced.
  3. Return a clean, executable SQL string.

Raises ValueError with a user-safe message on any violation.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

ALLOWED_TABLES = frozenset({"sales_data", "timesheet_data"})

# Keywords that must never appear at the top level of an allowed statement.
_FORBIDDEN_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "REPLACE", "MERGE", "GRANT", "REVOKE",
    "EXECUTE", "EXEC", "CALL", "COPY", "VACUUM", "ANALYZE",
})


def _strip_sql(sql: str) -> str:
    """Remove leading/trailing whitespace and trailing semicolons."""
    sql = sql.strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    return sql


def validate_sql(raw_sql: str) -> str:
    """
    Validate that `raw_sql` is a safe SELECT-only query referencing only
    allowed tables. Returns the cleaned SQL string ready for execution.

    Raises:
        ValueError — with a user-safe reason string if validation fails.
    """
    try:
        import sqlglot  # type: ignore[import]
        import sqlglot.expressions as exp  # type: ignore[import]
    except ImportError:
        # Fallback to regex-based validation if sqlglot is not installed.
        return _regex_validate(raw_sql)

    cleaned = _strip_sql(raw_sql)
    if not cleaned:
        raise ValueError("The model returned an empty query.")

    # --- Parse ---
    try:
        statements = sqlglot.parse(cleaned, dialect="postgres")
    except Exception as exc:
        raise ValueError(f"Could not parse the generated SQL: {exc}") from exc

    if not statements:
        raise ValueError("No SQL statement was generated.")

    if len(statements) > 1:
        raise ValueError("Only a single SQL statement is allowed per request.")

    stmt = statements[0]
    if stmt is None:
        raise ValueError("Empty SQL statement.")

    # --- Statement type check ---
    if not isinstance(stmt, exp.Select):
        kind = type(stmt).__name__
        raise ValueError(
            f"Only SELECT queries are allowed. The model generated a {kind} statement."
        )

    # --- Table whitelist ---
    # Find all Common Table Expression (CTE) names to avoid blocking local virtual tables.
    cte_names = {
        cte.alias.lower()
        for cte in stmt.find_all(exp.CTE)
        if cte.alias
    }
    referenced = {
        t.name.lower()
        for t in stmt.find_all(exp.Table)
    }
    physical_tables = referenced - cte_names
    disallowed = physical_tables - ALLOWED_TABLES
    if disallowed:
        raise ValueError(
            f"Query references disallowed table(s): {', '.join(sorted(disallowed))}. "
            f"Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}."
        )

    # --- No subquery DML (extra paranoia) ---
    for node in stmt.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create)):
            raise ValueError("Nested DML/DDL detected in query — blocked for safety.")

    logger.info("SQL validated OK. Referenced tables: %s", referenced)
    return cleaned


def _regex_validate(raw_sql: str) -> str:
    """Fallback validator used when sqlglot is not available."""
    cleaned = _strip_sql(raw_sql)
    upper = cleaned.upper()

    # Must start with SELECT
    if not re.match(r"^\s*SELECT\b", cleaned, re.IGNORECASE):
        raise ValueError("Only SELECT queries are permitted.")

    # Check for forbidden keywords
    for kw in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", upper):
            raise ValueError(
                f"Forbidden keyword '{kw}' detected in query. "
                "Only SELECT statements are allowed."
            )

    # Table whitelist via regex
    table_matches = re.findall(
        r"\bFROM\s+(\w+)|\bJOIN\s+(\w+)", cleaned, re.IGNORECASE
    )
    for match in table_matches:
        table = (match[0] or match[1]).lower()
        if table and table not in ALLOWED_TABLES:
            raise ValueError(
                f"Query references disallowed table '{table}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_TABLES))}."
            )

    return cleaned
    return cleaned
