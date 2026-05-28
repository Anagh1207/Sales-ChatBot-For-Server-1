"""
Build and execute safe, parameterized analytics queries against reflected tables.
No user-controlled SQL fragments are concatenated into statements.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import DateTime, Numeric, String, and_, cast, extract, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.table_metadata import reflect_table, resolve_column

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    """Normalize DB driver types for JSON responses."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # pragma: no cover
            return str(value)
    return value


def _sanitize_rows(rows: list[list[Any]]) -> list[list[Any]]:
    return [[_json_safe(v) for v in row] for row in rows]


def _as_date_column(col):
    """Cast to DateTime for filtering; works for TIMESTAMP or parseable TEXT in PG."""
    return cast(col, DateTime())


def _numeric_expr(col):
    return cast(col, Numeric(24, 4))


def _apply_time_filters(
    stmt,
    date_col,
    params: dict[str, Any],
):
    """
    Prefer explicit date ranges over calendar year/quarter to avoid conflicting filters.
    """
    if params.get("start_date") or params.get("end_date"):
        if params.get("start_date"):
            stmt = stmt.where(
                _as_date_column(date_col) >= func.cast(params["start_date"], DateTime())
            )
        if params.get("end_date"):
            stmt = stmt.where(
                _as_date_column(date_col) <= func.cast(params["end_date"], DateTime())
            )
        return stmt

    if params.get("quarter"):
        year_val = params.get("year") or date.today().year
        stmt = stmt.where(
            and_(
                extract("year", _as_date_column(date_col)) == year_val,
                extract("quarter", _as_date_column(date_col)) == params["quarter"],
            )
        )
        return stmt

    if params.get("year"):
        stmt = stmt.where(extract("year", _as_date_column(date_col)) == params["year"])
    return stmt


def _customer_filter(stmt, customer_col, needle: str):
    pattern = f"%{needle.strip()}%"
    return stmt.where(cast(customer_col, String).ilike(pattern))


def _salesperson_filter(stmt, sp_col, needle: str):
    pattern = f"%{needle.strip()}%"
    return stmt.where(cast(sp_col, String).ilike(pattern))


def run_intent_query(engine: Engine, db: Session, intent: str, params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a whitelisted intent. Returns dict with keys: columns, rows, summary (optional).
    Raises ValueError with user-safe message on missing tables/columns.
    """
    sales = reflect_table(engine, "sales_data")
    if sales is None:
        raise ValueError("sales_data table is not available. Run ingestion first.")

    date_col = resolve_column(sales, "sale_date", "saledate", "date")
    price_col = resolve_column(sales, "contract_price", "price", "amount")
    cust_col = resolve_column(sales, "customer_code", "customer", "customer_name")
    sp_col = resolve_column(sales, "sales_person", "salesperson", "sales_rep", "rep")

    if not date_col or not price_col:
        raise ValueError("Required sales columns (date, price) could not be resolved after ingestion.")

    price = sales.c[price_col]
    sdate = sales.c[date_col]
    customer = sales.c[cust_col] if cust_col else None
    salesperson = sales.c[sp_col] if sp_col else None

    intent_key = intent
    params = dict(params)
    params = {k: v for k, v in params.items() if v not in ("", None)}

    if intent_key == "sales_summary":
        stmt = select(
            func.sum(_numeric_expr(price)).label("total_sales_gbp"),
            func.count().label("rows"),
        ).select_from(sales)
        stmt = _apply_time_filters(stmt, sdate, params)
        if params.get("customer") and customer is not None:
            stmt = _customer_filter(stmt, customer, str(params["customer"]))
        if params.get("salesperson") and salesperson is not None:
            stmt = _salesperson_filter(stmt, salesperson, str(params["salesperson"]))
        row = db.execute(stmt).one()
        cols = ["total_sales_gbp", "rows"]
        data = _sanitize_rows([[row.total_sales_gbp, row.rows]])
        total = row.total_sales_gbp or 0
        return {
            "columns": cols,
            "rows": data,
            "summary": f"Total contract value in scope: £{float(total):,.2f}",
        }

    if intent_key == "top_customers":
        if customer is None:
            raise ValueError("Customer column not found; cannot compute top customers.")
        limit = int(params.get("limit", 5))
        stmt = (
            select(
                cast(customer, String).label("customer"),
                func.sum(_numeric_expr(price)).label("total_sales_gbp"),
            )
            .select_from(sales)
            .group_by(customer)
            .order_by(func.sum(_numeric_expr(price)).desc())
            .limit(limit)
        )
        stmt = _apply_time_filters(stmt, sdate, params)
        res = db.execute(stmt).all()
        cols = ["customer", "total_sales_gbp"]
        rows = _sanitize_rows([[r.customer, r.total_sales_gbp] for r in res])
        return {"columns": cols, "rows": rows, "summary": f"Top {limit} customers by contract value."}

    if intent_key == "salesperson_performance":
        if salesperson is None:
            raise ValueError("Salesperson column not found.")
        stmt = (
            select(
                cast(salesperson, String).label("salesperson"),
                func.sum(_numeric_expr(price)).label("total_sales_gbp"),
            )
            .select_from(sales)
            .group_by(salesperson)
            .order_by(func.sum(_numeric_expr(price)).desc())
        )
        stmt = _apply_time_filters(stmt, sdate, params)
        res = db.execute(stmt).all()
        cols = ["salesperson", "total_sales_gbp"]
        rows = _sanitize_rows([[r.salesperson, r.total_sales_gbp] for r in res])
        return {"columns": cols, "rows": rows, "summary": "Sales totals by salesperson."}

    if intent_key in ("yearly_sales", "quarterly_sales"):
        if intent_key == "yearly_sales":
            stmt = (
                select(
                    extract("year", _as_date_column(sdate)).label("year"),
                    func.sum(_numeric_expr(price)).label("total_sales_gbp"),
                )
                .select_from(sales)
                .group_by(extract("year", _as_date_column(sdate)))
                .order_by(extract("year", _as_date_column(sdate)))
            )
        else:
            stmt = (
                select(
                    extract("year", _as_date_column(sdate)).label("year"),
                    extract("quarter", _as_date_column(sdate)).label("quarter"),
                    func.sum(_numeric_expr(price)).label("total_sales_gbp"),
                )
                .select_from(sales)
                .group_by(
                    extract("year", _as_date_column(sdate)),
                    extract("quarter", _as_date_column(sdate)),
                )
                .order_by(
                    extract("year", _as_date_column(sdate)),
                    extract("quarter", _as_date_column(sdate)),
                )
            )
        stmt = _apply_time_filters(stmt, sdate, params)
        res = db.execute(stmt).all()
        if intent_key == "yearly_sales":
            cols = ["year", "total_sales_gbp"]
            rows = _sanitize_rows([[int(r.year), r.total_sales_gbp] for r in res])
        else:
            cols = ["year", "quarter", "total_sales_gbp"]
            rows = _sanitize_rows([[int(r.year), int(r.quarter), r.total_sales_gbp] for r in res])
        label = "Yearly" if intent_key == "yearly_sales" else "Quarterly"
        return {"columns": cols, "rows": rows, "summary": f"{label} sales aggregation."}

    if intent_key == "target_achievement":
        if salesperson is None:
            raise ValueError("Salesperson column not found for target view.")
        stmt = (
            select(
                cast(salesperson, String).label("salesperson"),
                func.sum(_numeric_expr(price)).label("total_sales_gbp"),
            )
            .select_from(sales)
            .group_by(salesperson)
        )
        stmt = _apply_time_filters(stmt, sdate, params)
        res = db.execute(stmt).all()
        quotas = settings.parsed_sales_quotas()
        default_q = float(settings.default_sales_quota_gbp)

        rows_out: list[list[Any]] = []
        for r in res:
            name = (r.salesperson or "").strip()
            total = float(r.total_sales_gbp or 0)
            quota = quotas.get(name) or quotas.get(name.split()[0]) or default_q
            pct = round((total / quota) * 100, 2) if quota else None
            rows_out.append([name, total, quota, pct])

        cols = ["salesperson", "total_sales_gbp", "quota_gbp", "achievement_pct"]
        met_only = bool(params.get("met_only"))
        not_met_only = bool(params.get("not_met_only"))
        filtered = []
        for row in rows_out:
            pct = row[3]
            if pct is None:
                continue
            if met_only and pct < 100:
                continue
            if not_met_only and pct >= 100:
                continue
            filtered.append(row)

        parts = [
            f"{row[0]} achieved {row[3]}% of quota (£{row[1]:,.0f} vs £{row[2]:,.0f})"
            for row in (filtered or rows_out)
            if row[3] is not None
        ]
        summary = "; ".join(parts) if parts else "No salesperson rows matched the filters."
        return {"columns": cols, "rows": _sanitize_rows(filtered or rows_out), "summary": summary}

    raise ValueError(f"Unsupported intent: {intent}")
