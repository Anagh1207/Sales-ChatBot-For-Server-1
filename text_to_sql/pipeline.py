"""
pipeline.py — Orchestrates the full Text-to-SQL flow.

Supports two backends selectable per request:
    "llama"     → sql_generator.py      (meta-llama/llama-3.3-70b-instruct)
    "sqlcoder"  → sql_generator_sqlcoder.py (defog/sqlcoder-70b-alpha)

Pipeline steps (both backends):
    1. Schema context  — reflect DB schema (format differs per backend)
    2. SQL generation  — backend-specific prompt → SQL
    3. SQL validation  — sqlglot AST: SELECT-only, whitelisted tables
    4. SQL execution   — SQLAlchemy text(), 200-row cap
    5. Summarization   — LLM → natural language answer

Returns a dict with: message, sql, table, error, truncated, backend.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.schemas import ChatMessage
from text_to_sql.schema_context import build_schema_context
from text_to_sql.schema_context_ddl import build_ddl_schema
from text_to_sql.sql_executor import execute_sql
from text_to_sql.sql_generator import generate_sql
from text_to_sql.sql_generator_sqlcoder import generate_sql_sqlcoder
from text_to_sql.response_formatter import generate_summary
from text_to_sql.sql_validator import validate_sql

logger = logging.getLogger(__name__)

Backend = Literal["llama", "sqlcoder"]
_VALID_BACKENDS: frozenset[str] = frozenset({"llama", "sqlcoder"})


def run_text_to_sql(
    db: Session,
    engine: Engine,
    user_message: str,
    history: list[ChatMessage],
    backend: Backend = "llama",
) -> dict[str, Any]:
    """
    Execute the complete Text-to-SQL pipeline with the chosen backend.

    Args:
        db:           SQLAlchemy session.
        engine:       SQLAlchemy engine.
        user_message: Natural language question.
        history:      Prior conversation turns.
        backend:      "llama" or "sqlcoder".

    Returns:
        {message, sql, table, error, truncated, backend}
    """
    trimmed = user_message.strip()
    if not trimmed:
        return _error_response("Please enter a question.", sql="", backend=backend)

    if backend not in _VALID_BACKENDS:
        return _error_response(
            f"Unknown backend '{backend}'. Choose 'llama' or 'sqlcoder'.",
            sql="", backend=backend,
        )

    history_dicts = [{"role": m.role, "content": m.content} for m in history]

    # ── 0. Bypasses for conversational and schema metadata requests ───────
    msg_lower = trimmed.lower()
    
    # 1. Chitchat / Greetings bypass
    greetings = {"hello", "hi", "hey", "hola", "greetings", "good morning", "good afternoon", "good evening", "who are you"}
    is_greeting = msg_lower in greetings or any(msg_lower.startswith(g + " ") for g in greetings)
    if is_greeting:
        return {
            "message": (
                "Hello! I am your Sales V2 AI Agent. I can help you query, analyze, and reason about the consolidated "
                "sales database (`sales_data`). You can ask me commercial questions like:\n\n"
                "- *\"What is our YoY growth between 2024 and 2025?\"*\n"
                "- *\"Show retrofit product sales trends.\"*\n"
                "- *\"Which customers bought cladding?\"*\n\n"
                "I will generate, validate, and execute PostgreSQL queries live to fetch the answer."
            ),
            "sql": "",
            "table": None,
            "error": None,
            "truncated": False,
            "backend": backend,
        }
        
    # 2. Schema / Metadata request bypass
    schema_keywords = {
        "schema", "table list", "database structure", "table structure", 
        "columns", "describe", "what tables", "list tables", "database schema"
    }
    is_schema_request = any(kw in msg_lower for kw in schema_keywords)
    if is_schema_request:
        try:
            from app.core.config import settings
            from openai import OpenAI
            
            schema_context = build_schema_context(engine)
            client = OpenAI(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
            )
            
            prompt = (
                "You are an expert sales analyst and database architect. "
                "The user is asking about the database schema. "
                "Using the live reflected schema context below, write a comprehensive, friendly, and structured "
                "response in Markdown explaining the table structure, available columns, dynamic categories (like insulation, cladding, MMC), "
                "and semantic mappings. Highlight the primary column names clearly so the user knows what they can ask.\n\n"
                f"DATABASE SCHEMA CONTEXT:\n{schema_context}"
            )
            
            resp = client.chat.completions.create(
                model=settings.text_to_sql_model,
                messages=[
                    {"role": "system", "content": "You are a helpful database assistant. Use Markdown list items, headers, and tables."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            summary = (resp.choices[0].message.content or "").strip()
            return {
                "message": summary,
                "sql": "",
                "table": None,
                "error": None,
                "truncated": False,
                "backend": backend,
            }
        except Exception as e:
            logger.error("Failed to generate schema explanation: %s", e)
            # Fallback static response
            return {
                "message": (
                    "Here is the database schema for the consolidated sales database:\n\n"
                    "### **Table: `sales_data`**\n"
                    "- `id` (INTEGER, Primary Key)\n"
                    "- `sale_date` (TIMESTAMP)\n"
                    "- `customer_code` (TEXT)\n"
                    "- `sales_person` (TEXT)\n"
                    "- `work_stream` (TEXT)\n"
                    "- `country` (TEXT)\n"
                    "- `city` (TEXT)\n"
                    "- `job_type` (TEXT)\n"
                    "- `product_type` (TEXT)\n"
                    "- `contract_price` (NUMERIC)\n\n"
                    "Feel free to ask me to analyze any of these columns!"
                ),
                "sql": "",
                "table": None,
                "error": None,
                "truncated": False,
                "backend": backend,
            }

    # ── 1. Schema context ──────────────────────────────────────────────────
    try:
        if backend == "sqlcoder":
            schema = build_ddl_schema(engine)   # CREATE TABLE DDL format
        else:
            schema = build_schema_context(engine)  # informal TABLE (...) format
    except Exception as exc:
        logger.error("Schema reflection failed [%s]: %s", backend, exc)
        return _error_response(
            "Could not read the database schema. "
            "Make sure the Excel data has been ingested first.",
            sql="", backend=backend,
        )

    # ── 2. SQL generation ──────────────────────────────────────────────────
    try:
        if backend == "sqlcoder":
            raw_sql = generate_sql_sqlcoder(schema, trimmed)
        else:
            raw_sql = generate_sql(schema, trimmed, history=history_dicts)
    except RuntimeError as exc:
        return _error_response(str(exc), sql="", backend=backend)

    # ── 3. SQL validation ──────────────────────────────────────────────────
    try:
        safe_sql = validate_sql(raw_sql)
    except ValueError as exc:
        logger.warning("SQL validation rejected [%s]: %s | SQL: %s", backend, exc, raw_sql)
        return _error_response(
            f"The generated query was blocked by safety checks: {exc}",
            sql=raw_sql, backend=backend,
        )

    # ── 4. SQL execution ───────────────────────────────────────────────────
    try:
        result = execute_sql(engine, db, safe_sql)
    except RuntimeError as exc:
        return _error_response(str(exc), sql=safe_sql, backend=backend)

    columns: list[str] = result["columns"]
    rows: list[list] = result["rows"]
    truncated: bool = result["truncated"]

    # ── 5. Response formatting ─────────────────────────────────────────────
    summary = generate_summary(
        user_question=trimmed,
        sql=safe_sql,
        columns=columns,
        rows=rows,
        truncated=truncated,
    )

    table_payload = {"columns": columns, "rows": rows} if columns else None

    return {
        "message": summary,
        "sql": safe_sql,
        "table": table_payload,
        "error": None,
        "truncated": truncated,
        "backend": backend,
    }


def _error_response(message: str, sql: str, backend: str) -> dict[str, Any]:
    return {
        "message": message,
        "sql": sql,
        "table": None,
        "error": message,
        "truncated": False,
        "backend": backend,
    }
