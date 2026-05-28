"""
OpenRouter client (OpenAI-compatible) for optional intent/entity extraction.
Used only when rule-based confidence is low or parsing fails.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_INTENTS = {
    "chitchat",
    "sales_summary",
    "top_customers",
    "target_achievement",
    "salesperson_performance",
    "yearly_sales",
    "quarterly_sales",
}

# Module-level singleton – constructed once, reused for every request.
# This avoids recreating the HTTP connection pool on each low-confidence query.
_client: OpenAI | None = (
    OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
    )
    if settings.openrouter_api_key
    else None
)


def refine_intent_with_llm(user_message: str) -> dict[str, Any] | None:
    """
    Ask the model to emit strict JSON with intent + parameters.
    Returns None if API key missing or call fails.
    Only called when rule-based confidence < 0.55 – minimises API usage.
    """
    if _client is None:
        logger.info("OPENROUTER_API_KEY not set; skipping LLM intent refinement.")
        return None

    system = (
        "You classify user messages into JSON only. "
        f"Allowed intents: {sorted(ALLOWED_INTENTS)}. "
        "Use intent \"chitchat\" for greetings, thanks, or unrelated small talk (no SQL). "
        "For analytics intents, parameters may include: year (int), quarter (1-4), limit (int), "
        "customer (string), salesperson (string), start_date (ISO date), end_date (ISO date), "
        "met_only (bool), not_met_only (bool). "
        "Respond with a single JSON object: "
        '{"intent":"...","parameters":{...},"confidence":0-1} '
        "No markdown, no prose."
    )

    try:
        resp = _client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=400,
        )
        content = (resp.choices[0].message.content or "").strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.I | re.M).strip()
        data = json.loads(content)
        intent = data.get("intent")
        if intent not in ALLOWED_INTENTS:
            return None
        params = data.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        data["parameters"] = params
        return data
    except Exception as exc:  # pragma: no cover - network
        logger.warning("LLM intent refinement failed: %s", exc)
        return None
