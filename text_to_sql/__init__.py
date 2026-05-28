"""
text_to_sql — LLM-powered natural language to SQL pipeline.

Public API:
    run_text_to_sql(db, engine, user_message, history) -> ChatResponse
"""
from text_to_sql.pipeline import run_text_to_sql  # noqa: F401

__all__ = ["run_text_to_sql"]
