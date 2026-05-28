"""
Application configuration loaded from environment variables.
Never commit secrets; use a local .env file (see README).
"""
from functools import lru_cache
import json
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/business_chatbot",
        description="SQLAlchemy database URL",
    )

    # OpenRouter (OpenAI-compatible client)
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    openrouter_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        alias="OPENROUTER_MODEL",
    )
    text_to_sql_model: str = Field(
        default="meta-llama/llama-3.3-70b-instruct",
        alias="TEXT_TO_SQL_MODEL",
    )
    sqlcoder_model: str = Field(
        default="defog/sqlcoder-70b-alpha",
        alias="SQLCODER_MODEL",
    )

    # Paths
    data_dir: str = Field(default="data", alias="DATA_DIR")
    sales_excel_path: str = Field(default="data/Sales.xlsx", alias="SALES_EXCEL_PATH")
    timesheet_excel_path: str = Field(
        default="data/Timesheet.xlsx", alias="TIMESHEET_EXCEL_PATH"
    )

    # Default GBP quota per salesperson when SALES_QUOTAS_JSON has no entry
    default_sales_quota_gbp: float = Field(default=200_000.0, alias="DEFAULT_SALES_QUOTA_GBP")

    # Optional JSON map: {"Mike": 300000, "JJ Smith": 250000}
    sales_quotas_json: str | None = Field(default=None, alias="SALES_QUOTAS_JSON")

    def parsed_sales_quotas(self) -> dict[str, float]:
        if not self.sales_quotas_json:
            return {}
        try:
            raw: dict[str, Any] = json.loads(self.sales_quotas_json)
            return {str(k): float(v) for k, v in raw.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
