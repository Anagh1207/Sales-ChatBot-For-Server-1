"""
Reflect and cache table metadata for Excel-backed tables (sales_data, timesheet_data).
Used by the query builder to resolve normalized column names safely.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

ALLOWED_TABLES = frozenset({"sales_data", "timesheet_data"})

# Module-level reflection cache – avoids re-querying PostgreSQL metadata on every request.
_TABLE_CACHE: dict[str, Table] = {}


def normalize_header(name: str) -> str:
    """Convert arbitrary Excel header to snake_case identifier."""
    s = str(name).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "column_unknown"
    if s[0].isdigit():
        s = f"col_{s}"
    return s


def reflect_table(engine: Engine, table_name: str) -> Table | None:
    """Return a reflected Table, using a module-level cache to avoid per-request DB round-trips."""
    if table_name not in ALLOWED_TABLES:
        return None
    if table_name in _TABLE_CACHE:
        return _TABLE_CACHE[table_name]
    md = MetaData()
    try:
        tbl = Table(table_name, md, autoload_with=engine)
        _TABLE_CACHE[table_name] = tbl
        logger.info("Reflected and cached table: %s", table_name)
        return tbl
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not reflect table %s: %s", table_name, exc)
        return None


def invalidate_table_cache(table_name: str | None = None) -> None:
    """Clear the reflection cache. Call after ingestion so fresh schema is loaded."""
    if table_name:
        _TABLE_CACHE.pop(table_name, None)
        logger.info("Invalidated table cache for: %s", table_name)
    else:
        _TABLE_CACHE.clear()
        logger.info("Cleared entire table reflection cache.")


def column_map(table: Table) -> dict[str, str]:
    """Lowercase column key -> actual column name on table."""
    return {c.name.lower(): c.name for c in table.columns}


def resolve_column(table: Table, *candidates: str) -> str | None:
    """Pick first matching column from normalized candidate names."""
    cmap = column_map(table)
    for cand in candidates:
        key = normalize_header(cand)
        if key in cmap:
            return cmap[key]
        if cand.lower() in cmap:
            return cmap[cand.lower()]
    return None
