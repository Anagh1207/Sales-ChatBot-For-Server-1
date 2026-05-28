"""
text_to_sql_routes.py — FastAPI router for the Text-to-SQL chat endpoints.

POST /text-to-sql/chat
    Accepts optional `backend` field: "llama" | "sqlcoder" (default: "llama")

POST /text-to-sql/bust-cache
    Clears both schema caches (call after ingesting new Excel data).
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import engine, get_db
from app.models.schemas import ChatMessage
from text_to_sql.pipeline import run_text_to_sql
from text_to_sql.schema_context import bust_schema_cache
from text_to_sql.schema_context_ddl import bust_ddl_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/text-to-sql", tags=["text-to-sql"])


# ── Request / Response schemas ─────────────────────────────────────────────

class TextToSqlRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)
    backend: Literal["llama", "sqlcoder"] = Field(
        default="llama",
        description="'llama' = llama-3.3-70b-instruct | 'sqlcoder' = defog/sqlcoder-70b-alpha",
    )


class TablePayload(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class TextToSqlResponse(BaseModel):
    message: str
    sql: str = ""
    table: TablePayload | None = None
    error: str | None = None
    truncated: bool = False
    backend: str = "llama"


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/chat", response_model=TextToSqlResponse)
def text_to_sql_chat(
    payload: TextToSqlRequest,
    db: Session = Depends(get_db),
):
    """
    Convert a natural language question to SQL using the selected backend.

    - backend="llama"    → meta-llama/llama-3.3-70b-instruct (general LLM)
    - backend="sqlcoder" → defog/sqlcoder-70b-alpha (SQL-specialized model)
    """
    try:
        result = run_text_to_sql(
            db=db,
            engine=engine,
            user_message=payload.message,
            history=payload.history,
            backend=payload.backend,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Unhandled error in text-to-sql pipeline [%s]", payload.backend)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    table_data = result.get("table")
    table_payload = (
        TablePayload(
            columns=table_data["columns"],
            rows=table_data["rows"],
        )
        if table_data
        else None
    )

    return TextToSqlResponse(
        message=result["message"],
        sql=result.get("sql", ""),
        table=table_payload,
        error=result.get("error"),
        truncated=result.get("truncated", False),
        backend=result.get("backend", payload.backend),
    )


@router.post("/bust-cache")
def bust_cache():
    """Clear all schema reflection caches (call after ingesting new data)."""
    bust_schema_cache()
    bust_ddl_cache()
    return {"status": "ok", "detail": "Both schema caches cleared."}
