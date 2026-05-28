"""
schema_context_ddl.py — Generates CREATE TABLE DDL strings from the live
PostgreSQL schema, formatted specifically for SQLCoder's prompt template.

SQLCoder was fine-tuned on standard CREATE TABLE DDL, so this format gives
significantly better SQL generation than the informal TABLE (...) format
used for general LLMs.

Cache is separate from schema_context.py to allow independent invalidation.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

ALLOWED_TABLES = frozenset({"sales_data", "timesheet_data"})

_ddl_cache: dict[int, str] = {}  # engine id → DDL string


def _pg_type_ddl(col_type: str) -> str:
    """Map SQLAlchemy type repr → standard PostgreSQL DDL type."""
    t = str(col_type).upper()
    if "BIGINT" in t:
        return "BIGINT"
    if "INT" in t:
        return "INTEGER"
    if "NUMERIC" in t or "DECIMAL" in t:
        return "NUMERIC(18,4)"
    if "FLOAT" in t or "REAL" in t or "DOUBLE" in t:
        return "FLOAT"
    if "TIMESTAMP" in t:
        return "TIMESTAMP"
    if "DATE" in t:
        return "DATE"
    if "BOOL" in t:
        return "BOOLEAN"
    if "VARCHAR" in t or "CHAR" in t:
        return "VARCHAR"
    return "TEXT"


def build_ddl_schema(engine: Engine) -> str:
    """
    Return a CREATE TABLE DDL string for all allowed tables, e.g.:

        CREATE TABLE sales_data (
            id INTEGER,
            sale_date TIMESTAMP,
            customer_code TEXT,
            ...
        );

        CREATE TABLE timesheet_data (
            ...
        );

    This format is what SQLCoder was trained on.
    """
    key = id(engine)
    if key in _ddl_cache:
        return _ddl_cache[key]

    inspector = inspect(engine)
    parts: list[str] = []

    for table_name in sorted(ALLOWED_TABLES):  # deterministic order
        try:
            columns = inspector.get_columns(table_name)
            pk_cols = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
        except Exception:
            logger.warning("Could not inspect table for DDL: %s", table_name)
            continue

        col_defs: list[str] = []
        for col in columns:
            name = col["name"]
            dtype = _pg_type_ddl(str(col["type"]))
            nullable = "" if col.get("nullable", True) else " NOT NULL"
            pk = " PRIMARY KEY" if name in pk_cols else ""
            col_defs.append(f"    {name} {dtype}{nullable}{pk}")

        block = (
            f"CREATE TABLE {table_name} (\n"
            + ",\n".join(col_defs)
            + "\n);"
        )
        parts.append(block)

    ddl_str = "\n\n".join(parts) if parts else "-- (no tables ingested yet)"
    _ddl_cache[key] = ddl_str
    logger.info("Built DDL schema context (%d chars) for SQLCoder", len(ddl_str))
    return ddl_str


def bust_ddl_cache(engine: Optional[Engine] = None) -> None:
    """Clear the DDL cache — call after ingestion."""
    if engine is not None:
        _ddl_cache.pop(id(engine), None)
    else:
        _ddl_cache.clear()
    logger.info("DDL schema cache cleared.")
