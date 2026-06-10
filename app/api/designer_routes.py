"""
designer_routes.py — Clean, designer-focused API endpoints for custom frontend integration.
"""
from __future__ import annotations

import logging
from typing import Any, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import engine, get_db
from app.models.schemas import ChatMessage, TablePayload
from text_to_sql.pipeline import run_text_to_sql

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["designer-api"])


class DesignerChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="The natural language question or message from the user.")
    history: list[ChatMessage] = Field(default_factory=list, description="Prior conversation history for carry-over context.")


class DesignerChatResponse(BaseModel):
    answer: str = Field(..., description="Markdown response containing the business explanation and reasoning with rounded EDP figures.")
    sql_query: str = Field("", description="The safe SQL SELECT statement generated and run (empty if chitchat/metadata query).")
    data_table: TablePayload | None = Field(None, description="Structured dataset matching the query results.")
    has_data: bool = Field(False, description="Boolean flag indicating if a valid tabular dataset is included.")
    error: str | None = Field(None, description="Error details if the pipeline failed or SQL was blocked by safety checks.")


@router.post("/chat", response_model=DesignerChatResponse)
def designer_chat(
    payload: DesignerChatRequest,
    db: Session = Depends(get_db),
):
    """
    Unified API Endpoint for Frontend Designers:
    
    Converts a natural language query into clean SQL, runs it against the PostgreSQL database,
    and returns a formatted Markdown response with rounded EDP currency values along with tabular data.
    """
    try:
        # We run the primary Llama pipeline
        result = run_text_to_sql(
            db=db,
            engine=engine,
            user_message=payload.message,
            history=payload.history,
            backend="llama",
        )
    except Exception as exc:
        logger.exception("Designer API call failed")
        return DesignerChatResponse(
            answer="⚠️ An unexpected server error occurred while processing your request.",
            sql_query="",
            data_table=None,
            has_data=False,
            error=str(exc),
        )

    # Prepare table payload if data is present
    table_data = result.get("table")
    table_payload = None
    has_data = False
    
    if table_data and table_data.get("columns") and table_data.get("rows"):
        table_payload = TablePayload(
            columns=table_data["columns"],
            rows=table_data["rows"],
        )
        has_data = len(table_data["rows"]) > 0

    return DesignerChatResponse(
        answer=result.get("message", "No response explanation returned."),
        sql_query=result.get("sql", ""),
        data_table=table_payload,
        has_data=has_data,
        error=result.get("error"),
    )
