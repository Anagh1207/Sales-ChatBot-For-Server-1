"""
schema_context.py — Reflects live PostgreSQL tables and builds the LLM
system-prompt context string that describes the database schema.

Caches the schema string per engine; invalidate with `bust_schema_cache()`.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Tables the LLM is allowed to query.
ALLOWED_TABLES = frozenset({"sales_data"})

import threading
from sqlalchemy import select, distinct

_schema_cache: dict[int, str] = {}
_distinct_cache: dict[str, list[str]] = {}
_cache_lock = threading.Lock()


def _get_distinct_values(engine: Engine, column_name: str) -> list[str]:
    """Fetch distinct non-null values for a column in sales_data, with caching."""
    global _distinct_cache
    cache_key = f"{id(engine)}_{column_name}"
    
    with _cache_lock:
        if cache_key in _distinct_cache:
            return _distinct_cache[cache_key]
            
    try:
        from sqlalchemy import Table, MetaData
        metadata = MetaData()
        sales_table = Table("sales_data", metadata, autoload_with=engine)
        if column_name in sales_table.c:
            col = sales_table.c[column_name]
            stmt = select(distinct(col)).where(col.is_not(None)).order_by(col)
            with engine.connect() as conn:
                results = conn.execute(stmt).scalars().all()
                val_list = [str(r) for r in results if r]
                with _cache_lock:
                    _distinct_cache[cache_key] = val_list
                return val_list
    except Exception as exc:
        logger.warning("Could not fetch distinct values for %s: %s", column_name, exc)
        
    return []


def _pg_type_label(col_type: str) -> str:
    """Simplify SQLAlchemy type repr to a short SQL-friendly label."""
    t = str(col_type).upper()
    if "INT" in t:
        return "INTEGER"
    if "FLOAT" in t or "NUMERIC" in t or "DECIMAL" in t or "REAL" in t:
        return "NUMERIC"
    if "DATE" in t or "TIME" in t:
        return "TIMESTAMP"
    if "BOOL" in t:
        return "BOOLEAN"
    return "TEXT"


def build_schema_context(engine: Engine) -> str:
    """
    Return a DDL-like string describing all allowed tables, enriched with dynamic
    category vocabularies and zero-shot semantic mapping rules.
    """
    key = id(engine)
    if key in _schema_cache:
        return _schema_cache[key]

    inspector = inspect(engine)
    parts: list[str] = []

    for table_name in ALLOWED_TABLES:
        try:
            columns = inspector.get_columns(table_name)
        except Exception:
            logger.warning("Could not inspect table: %s", table_name)
            continue

        col_lines = []
        for col in columns:
            col_name = col["name"]
            col_type = _pg_type_label(str(col["type"]))
            nullable = "" if col.get("nullable", True) else " NOT NULL"
            col_lines.append(f"    {col_name} {col_type}{nullable}")

        parts.append(f"TABLE {table_name} (\n" + ",\n".join(col_lines) + "\n)")

    schema_str = "\n\n".join(parts) if parts else "(no tables ingested yet)"

    # Inject dynamic allowed categories & zero-shot semantic matching guide
    if "sales_data" in inspector.get_table_names():
        p_types = _get_distinct_values(engine, "product_type")
        j_types = _get_distinct_values(engine, "job_type")
        
        guide = (
            "\n\n==================================================\n"
            "ALLOWED VALUES AND SEMANTIC MATCHING GUIDANCE:\n\n"
            "1. DISTINCT PRODUCT TYPES currently in the database (Use exact matches in SQL):\n"
            f"   {p_types if p_types else '(None)'}\n\n"
            "2. DISTINCT JOB TYPES currently in the database (Can contain novel added values in future):\n"
            f"   {j_types if j_types else '(None)'}\n\n"
            "3. SEMANTIC CLASSIFICATION RULEBOOK:\n"
            "   - If user asks about 'Retrofit', 'Energy Efficiency', 'Sustainability' or 'Insulation', map to insulation products:\n"
            "     'BU - Built-in Cavity Wall Insulation', 'EW - External Wall Insulation', 'RI - Roof Insulation'\n"
            "   - If user asks about 'Facade Remediation', 'Facade', or 'Exterior cladding', map to cladding/board products:\n"
            "     'CL - Cladding', 'CS - Cladding Slate', 'LP - PVC-U Cladding', 'BQ - PVC-U Barge, Facia or Soffit Board'\n"
            "   - If user asks about 'MMC' (Modern Methods of Construction), 'Prefabricated' or 'Modular', map to building systems:\n"
            "     'TM - Building System', 'TR - Building - Relocatable', 'TB - Building Block'\n"
            "   - If user asks about 'Fire Testing' or 'Testing', map to the Work Stream: 'Test'\n"
            "   - If user mentions any other dynamic industry term (e.g., 'remedial works', 'roofing tile', 'waterproofing'), perform a zero-shot semantic match to find the most relevant string from DISTINCT PRODUCT TYPES above (e.g. 'remedial works' -> 'DR - Damp-proof Course (remedial)').\n"
            "   - If no close match exists in the category list, fall back to a SQL ILIKE pattern match on the respective column:\n"
            "     `CAST(product_type AS TEXT) ILIKE '%user_keyword%'`\n"
            "=================================================="
        )
        schema_str += guide

    _schema_cache[key] = schema_str
    logger.info("Built schema context (%d chars)", len(schema_str))
    return schema_str


def bust_schema_cache(engine: Optional[Engine] = None) -> None:
    """Clear schema cache and dynamic categories cache. Called after Excel ingestion."""
    global _distinct_cache
    if engine is not None:
        _schema_cache.pop(id(engine), None)
        with _cache_lock:
            for k in list(_distinct_cache.keys()):
                if k.startswith(f"{id(engine)}_"):
                    _distinct_cache.pop(k, None)
    else:
        _schema_cache.clear()
        with _cache_lock:
            _distinct_cache.clear()
    logger.info("Schema and distinct values caches cleared.")
