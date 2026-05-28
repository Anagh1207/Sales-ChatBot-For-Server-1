"""
FastAPI routers for analytics and chat.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db, engine
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    IngestResponse,
    SalesSummaryParams,
    SalespersonPerformanceParams,
    TargetAchievementParams,
    TopCustomersParams,
)
from app.query_builder.sales_analytics import run_intent_query
from app.services.chat_service import handle_chat_message
from app.services.excel_ingestion import ingest_all

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest, db: Session = Depends(get_db)):
    """Natural language interface backed by safe internal SQL generation."""
    return handle_chat_message(db, engine, payload.message, payload.history)


def _run(db: Session, intent: str, params: dict):
    try:
        return run_intent_query(engine, db, intent, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sales-summary")
def sales_summary(
    customer: str | None = None,
    salesperson: str | None = None,
    year: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    params = SalesSummaryParams(
        customer=customer,
        salesperson=salesperson,
        year=year,
        start_date=start_date,
        end_date=end_date,
    ).model_dump(exclude_none=True)
    return _run(db, "sales_summary", params)


@router.get("/top-customers")
def top_customers(
    limit: int = 5,
    year: int | None = None,
    quarter: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    params = TopCustomersParams(limit=limit, year=year, quarter=quarter).model_dump(exclude_none=True)
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _run(db, "top_customers", params)


@router.get("/target-achievement")
def target_achievement(
    year: int | None = None,
    quarter: int | None = None,
    met_only: bool | None = None,
    not_met_only: bool | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    params = TargetAchievementParams(
        year=year,
        quarter=quarter,
        met_only=met_only,
        not_met_only=not_met_only,
    ).model_dump(exclude_none=True)
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _run(db, "target_achievement", params)


@router.get("/salesperson-performance")
def salesperson_performance(
    year: int | None = None,
    quarter: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    params = SalespersonPerformanceParams(year=year, quarter=quarter).model_dump(exclude_none=True)
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _run(db, "salesperson_performance", params)


@router.post("/admin/ingest-excel", response_model=IngestResponse)
def ingest_excel():
    """
    Load configured Excel paths into PostgreSQL (destructive replace per table).
    Intended for local/dev; protect in production (auth omitted for MVP).
    """
    try:
        counts = ingest_all(engine)
    except Exception as exc:  # pragma: no cover
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return IngestResponse(status="ok", counts=counts)
