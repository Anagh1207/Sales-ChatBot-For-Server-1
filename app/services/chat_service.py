"""
High-level chat orchestration: intent detection, optional LLM refinement, query execution.
"""
from __future__ import annotations

import logging

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.intent_detection.entities import extract_customer_phrase, extract_salesperson_phrase
from app.intent_detection.rules import IntentResult, classify_intent
from app.query_builder.sales_analytics import run_intent_query
from app.models.schemas import ChatMessage, ChatResponse, TablePayload
from app.services.llm_service import refine_intent_with_llm

logger = logging.getLogger(__name__)


def _prior_user_context(history: list[ChatMessage], max_turns: int = 5) -> str:
    """Concatenate recent *prior* user lines only — used for entity carry-over, not intent keywords."""
    user_parts = [m.content for m in history if m.role == "user"][-max_turns:]
    return " \n".join(user_parts)


def enrich_params_from_prior_turns(result: IntentResult, history: list[ChatMessage]) -> IntentResult:
    """
    When the latest utterance is a short follow-up (e.g. year range only), recover
    customer/salesperson from earlier user messages in this session.
    """
    if result.intent not in ("sales_summary",):
        return result
    prev = _prior_user_context(history)
    if not prev.strip():
        return result
    params = dict(result.parameters)
    if not params.get("customer"):
        c = extract_customer_phrase(prev)
        if c:
            params["customer"] = c
    if not params.get("salesperson"):
        sp = extract_salesperson_phrase(prev)
        if sp:
            params["salesperson"] = sp
    if params == result.parameters:
        return result
    return IntentResult(
        intent=result.intent,
        confidence=result.confidence,
        parameters=params,
        needs_clarification=result.needs_clarification,
        clarification_question=result.clarification_question,
    )


def _merge_llm(base: IntentResult, llm_payload: dict[str, Any] | None) -> IntentResult:
    if not llm_payload:
        return base
    intent = llm_payload.get("intent") or base.intent
    # Never downgrade explicit rules-only intents like chitchat via LLM unless LLM agrees it's non-analytics.
    if base.intent == "chitchat":
        return base
    params = {**base.parameters, **(llm_payload.get("parameters") or {})}
    conf = float(llm_payload.get("confidence") or base.confidence)
    return IntentResult(intent=intent, confidence=max(conf, base.confidence), parameters=params)


def handle_chat_message(db: Session, engine, message: str, history: list[ChatMessage]) -> ChatResponse:
    trimmed = message.strip()
    
    # Check if the query is an analytical or complex business question
    analytical_keywords = [
        "growth", "decline", "retrofit", "churn", "cross-sell", "growing", "stopped buying", 
        "compare", "expand", "opportunities", "concentration", "dependency", "combination", 
        "associated", "buy usually", "most frequent", "best product"
    ]
    is_analytical = any(kw in trimmed.lower() for kw in analytical_keywords)
    
    # Classify intent for simple lookup routing
    detected = classify_intent(trimmed)
    detected = enrich_params_from_prior_turns(detected, history)

    if not is_analytical and detected.confidence < 0.55 and settings.openrouter_api_key:
        llm = refine_intent_with_llm(trimmed)
        detected = _merge_llm(detected, llm)

    # Route analytical or low-confidence lookup queries directly to the dynamic Text-to-SQL reasoning pipeline
    if is_analytical or (detected.intent not in ("chitchat", "sales_summary") and detected.confidence < 0.75):
        from text_to_sql.pipeline import run_text_to_sql
        try:
            res = run_text_to_sql(db, engine, trimmed, history, backend="llama")
            if not res.get("error"):
                table_payload = None
                if res.get("table"):
                    table_payload = TablePayload(columns=res["table"]["columns"], rows=res["table"]["rows"])
                return ChatResponse(
                    intent="text_to_sql",
                    message=res["message"],
                    needs_clarification=False,
                    parameters={},
                    table=table_payload,
                    meta={"sql": res.get("sql"), "dynamic": True}
                )
        except Exception as exc:
            logger.warning("Dynamic Text-to-SQL routing fallback failed: %s", exc)

    if detected.intent == "chitchat":
        return ChatResponse(
            intent=detected.intent,
            message=(
                "Hi — I can pull totals, top customers, quarterly/yearly breakdowns, and "
                "target attainment from your ingested sales data. Try: "
                "“total sales this year”, “top 5 customers this quarter”, or “who met target?”."
            ),
            parameters={},
        )

    if detected.needs_clarification:
        return ChatResponse(
            intent=detected.intent,
            message=detected.clarification_question or "Could you clarify the time period?",
            needs_clarification=True,
            clarification_question=detected.clarification_question,
            parameters=detected.parameters,
        )

    try:
        result = run_intent_query(engine, db, detected.intent, detected.parameters)
    except ValueError as exc:
        logger.warning("Query failed: %s", exc)
        return ChatResponse(
            intent=detected.intent,
            message=str(exc),
            parameters=detected.parameters,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected query error")
        return ChatResponse(
            intent=detected.intent,
            message="Something went wrong while querying the database.",
            parameters=detected.parameters,
            meta={"error": str(exc)},
        )

    table = TablePayload(columns=result["columns"], rows=result["rows"])
    summary = result.get("summary") or "Here are the results."
    return ChatResponse(
        intent=detected.intent,
        message=summary,
        needs_clarification=False,
        parameters=detected.parameters,
        table=table,
        meta={"confidence": detected.confidence},
    )
