"""
Pydantic schemas for API requests and responses.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., description="user | assistant | system")
    content: str


class ChatRequest(BaseModel):
    """Natural language chat request; optional history for short follow-ups."""

    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)


class TablePayload(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class ChatResponse(BaseModel):
    intent: str | None = None
    message: str
    needs_clarification: bool = False
    clarification_question: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    table: TablePayload | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class SalesSummaryParams(BaseModel):
    customer: str | None = None
    salesperson: str | None = None
    year: int | None = None
    start_date: str | None = None
    end_date: str | None = None


class TopCustomersParams(BaseModel):
    limit: int = Field(default=5, ge=1, le=50)
    year: int | None = None
    quarter: int | None = Field(default=None, ge=1, le=4)


class TargetAchievementParams(BaseModel):
    year: int | None = None
    quarter: int | None = Field(default=None, ge=1, le=4)
    met_only: bool | None = None
    not_met_only: bool | None = None


class SalespersonPerformanceParams(BaseModel):
    year: int | None = None
    quarter: int | None = Field(default=None, ge=1, le=4)


class IngestResponse(BaseModel):
    status: str
    counts: dict[str, int]
    detail: str | None = None
