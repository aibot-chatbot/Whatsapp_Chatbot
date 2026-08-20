"""
ai_usage_repository.py — Immutable AI usage log for per-request provider cost tracking.

Records one row per completed AI provider call. This is the authoritative
source for AI-credit deduction. The table is append-only: rows are never
updated or deleted after creation.
Token usage is recorded for telemetry (prompt, completion, and total tokens).
Provider cost is stored in micro-USD. Customer billing uses MYR AI credit.
The table is append-only: rows are never updated or deleted after creation.
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
    billing_fx_rate_micro_myr_per_usd: int | None = None,
    billing_markup_basis_points: int | None = None,
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
        billing_fx_rate_micro_myr_per_usd: USD-to-MYR rate snapshot at request time.
        billing_markup_basis_points: Markup snapshot in basis points at request time.

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
        "billing_fx_rate_micro_myr_per_usd": billing_fx_rate_micro_myr_per_usd,
        "billing_markup_basis_points": billing_markup_basis_points,
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


def get_usage_log_by_provider_generation_id(provider: str, generation_id: str) -> dict | None:
    """Look up an existing usage log by provider and generation ID.

    This supports duplicate detection and safe recovery: if a usage row
    was previously inserted but charging may have failed, the existing
    row can be found and re-charged without making another provider call.

    Args:
        provider: The provider identifier (e.g. "openrouter").
        generation_id: The generation ID returned by the provider.

    Returns:
        The existing usage-log record dictionary, or None if not found.

    Raises:
        ValueError: If provider or generation_id is empty.
    """
    if not provider or not provider.strip():
        raise ValueError("provider is required")
    if not generation_id or not generation_id.strip():
        raise ValueError("generation_id is required")

    response = (
        supabase
        .table(TABLE_NAME)
        .select("*")
        .eq("provider", provider)
        .eq("generation_id", generation_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    return rows[0] if rows else None


def list_company_completed_usage_by_range(
    company_id: int,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """Return completed usage logs for one company in a bounded date range."""
    if not company_id:
        raise ValueError("company_id is required")
    if not date_from or not date_to:
        raise ValueError("date_from and date_to are required")

    response = (
        supabase
        .table(TABLE_NAME)
        .select(
            "id,company_id,chatbot_id,provider,model,operation_type,"
            "request_status,prompt_tokens,completion_tokens,total_tokens,"
            "provider_cost_micro_usd,created_at"
        )
        .eq("company_id", company_id)
        .eq("request_status", "completed")
        .gte("created_at", date_from)
        .lt("created_at", date_to)
        .order("created_at", desc=False)
        .execute()
    )

    return response.data or []
