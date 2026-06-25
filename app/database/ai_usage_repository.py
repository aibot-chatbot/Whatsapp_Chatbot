"""
ai_usage_repository.py — Immutable AI usage log for per-request provider cost tracking.

Records one row per completed AI provider call. This is the authoritative
source for AI-credit deduction. The table is append-only: rows are never
updated or deleted after creation.

The existing monthly_ai_message_limit and the AI-credit accounting system
both read usage from this table for their respective periods.
"""

from datetime import datetime, timezone

from app.database.db import supabase


TABLE_NAME = "ai_usage_logs"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def insert_usage_log(
    company_id: int,
    chatbot_id: int,
    provider: str,
    model: str,
    operation_type: str = "chat_reply",
    request_status: str = "completed",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    reasoning_tokens: int = 0,
    cached_tokens: int = 0,
    provider_cost_micro_usd: int | None = None,
    generation_id: str = None,
    attempt_number: int = 1,
) -> dict | None:
    """Insert one immutable AI usage log entry.

    Validates required identifiers and non-negative numeric values.
    Returns the created record, or None on duplicate generation_id.

    Args:
        company_id: The company that owns the chatbot.
        chatbot_id: The chatbot that generated the AI response.
        provider: AI provider name (e.g. "openai", "deepseek", "google").
        model: Model identifier used (e.g. "openai/gpt-5.5").
        operation_type: Type of AI operation (e.g. "chat_reply", "test_chat").
        request_status: "completed" or "failed".
        prompt_tokens: Number of prompt tokens used.
        completion_tokens: Number of completion tokens used.
        total_tokens: Total tokens (prompt + completion).
        reasoning_tokens: Reasoning tokens (when available).
        cached_tokens: Cached/prompt-hit tokens (when available).
        provider_cost_micro_usd: Provider-side cost in micro-USD (None when unknown).
        generation_id: Provider generation ID for duplicate prevention.
        attempt_number: Attempt counter starting at 1.

    Returns:
        dict: The created usage log record.
        None: When a record with the same generation_id already exists.

    Raises:
        ValueError: If required identifiers are missing or values are negative.
    """
    if not company_id:
        raise ValueError("company_id is required")
    if not chatbot_id:
        raise ValueError("chatbot_id is required")
    if not provider:
        raise ValueError("provider is required")
    if not model:
        raise ValueError("model is required")

    _validate_non_negative(prompt_tokens, "prompt_tokens")
    _validate_non_negative(completion_tokens, "completion_tokens")
    _validate_non_negative(total_tokens, "total_tokens")
    _validate_non_negative(reasoning_tokens, "reasoning_tokens")
    _validate_non_negative(cached_tokens, "cached_tokens")
    _validate_non_negative(provider_cost_micro_usd, "provider_cost_micro_usd")

    payload = {
        "company_id": company_id,
        "chatbot_id": chatbot_id,
        "provider": provider,
        "model": model,
        "operation_type": operation_type,
        "request_status": request_status,
        "prompt_tokens": prompt_tokens if prompt_tokens else 0,
        "completion_tokens": completion_tokens if completion_tokens else 0,
        "total_tokens": total_tokens if total_tokens else 0,
        "reasoning_tokens": reasoning_tokens if reasoning_tokens else 0,
        "cached_tokens": cached_tokens if cached_tokens else 0,
        "provider_cost_micro_usd": provider_cost_micro_usd,
        "generation_id": generation_id,
        "attempt_number": attempt_number,
        "created_at": _now_iso(),
    }

    response = supabase.table(TABLE_NAME).insert(payload).execute()
    rows = response.data or []

    if not rows:
        # May be None when the unique index on generation_id rejects a duplicate
        return None

    return rows[0]


def _validate_non_negative(value: int | None, field_name: str):
    if value is not None and value < 0:
        raise ValueError(
            f"{field_name} must be non-negative, got {value}"
        )
