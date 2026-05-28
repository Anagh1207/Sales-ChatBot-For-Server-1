"""
Infer SQLAlchemy column types from pandas Series dtypes and build/create tables.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    inspect,
)
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable, DropTable

from app.services.table_metadata import ALLOWED_TABLES, normalize_header

logger = logging.getLogger(__name__)


def _sqlalchemy_type_for_series(series: pd.Series):
    """Map a pandas Series to a conservative SQLAlchemy type."""
    # Use non-null subset for inference when possible
    non_null = series.dropna()
    if non_null.empty:
        return Text()

    sample = non_null.iloc[0]

    if pd.api.types.is_bool_dtype(series):
        return String(16)
    if pd.api.types.is_integer_dtype(series):
        return Numeric(20, 0)
    if pd.api.types.is_float_dtype(series):
        return Numeric(20, 4)
    if pd.api.types.is_datetime64_any_dtype(series):
        return DateTime(timezone=False)

    # Object / mixed: inspect values
    if isinstance(sample, (datetime, date)):
        return DateTime(timezone=False)
    if isinstance(sample, (int,)):
        return Numeric(20, 0)
    if isinstance(sample, (float, Decimal)):
        return Numeric(20, 4)

    return Text()


def dataframe_to_table(
    df: pd.DataFrame,
    table_name: str,
    metadata: MetaData,
) -> Table:
    """Build a SQLAlchemy Table definition from a DataFrame."""
    if table_name not in ALLOWED_TABLES:
        raise ValueError(f"Unsupported table name: {table_name}")

    columns = []
    for col in df.columns:
        name = normalize_header(col)
        col_type = _sqlalchemy_type_for_series(df[col])
        columns.append(Column(name, col_type, nullable=True))

    # Guarantee an internal surrogate id for stable joins (optional) — skip to keep schema = Excel only

    return Table(table_name, metadata, *columns)


def normalize_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename DataFrame columns to normalized snake_case matching the Table."""
    out = df.copy()
    out.columns = [normalize_header(c) for c in out.columns]
    return out


def recreate_table_from_dataframe(engine: Engine, df: pd.DataFrame, table_name: str) -> None:
    """
    Drop (if exists) and create table, then bulk insert rows.
    MVP approach: full replace on each ingestion run.
    """
    md = MetaData()
    table = dataframe_to_table(df, table_name, md)

    with engine.begin() as conn:
        if inspect(conn).has_table(table_name):
            conn.execute(DropTable(table))
        conn.execute(CreateTable(table))

    # Use pandas to_sql for efficient insert (uses first chunk of dtypes)
    norm = normalize_dataframe_columns(df)
    row_count = len(norm)
    norm.to_sql(table_name, con=engine, if_exists="append", index=False, method="multi")
    logger.info("Loaded %s rows into %s", row_count, table_name)
