import logging
import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from app.services import deepseek_service
from app.services import openrouter_service
from app.services.chat_pipeline_service import prepare_chat_prompt
from app.services.model_catalog import (
    OPENROUTER_PROVIDER_KEYS,
    normalize_model_selection,
    get_default_model,
    is_model_allowed_for_tier,
    is_openrouter_model,
    get_model_tier,
    get_model_provider,
    validate_provider_model_pair,
)
from app.services.response_formatter import clean_ai_reply
from app.database.bot_repository import get_bot_by_id
from app.services.ai_access_policy import (
    resolve_ai_access,
    ROUTE_DIRECT_DEEPSEEK,
    ROUTE_OPENROUTER,
    ROUTE_DENIED,
    OPENROUTER_PROVIDER_FAMILIES,
    TRIAL_PROVIDER,
    TRIAL_MODEL,
)
from app.services.billing_guard import BillingLimitError
from app.services.ai_credit_service import (
    is_ai_credit_enforcement_enabled,
    get_ai_retail_markup_basis_points,
    get_ai_usd_to_myr_rate_micro_myr_per_usd,
    get_company_ai_credit_summary,
    charge_logged_ai_usage,
    ensure_company_ai_credit,
)

from app.services.billing_notification_service import (
    notify_ai_credit_low,
    notify_ai_credit_critical,
    notify_ai_credit_depleted,
)

from app.database.company_subscription_repository import get_company_subscription
from app.database.subscription_plan_repository import get_plan_by_id

from app.database.ai_usage_repository import insert_usage_log


FLOW_RUNTIME_FAILURE_REPLY = "Sorry, I'm having trouble replying right now. Please try again later."


def _flow_runtime_failed_result():
    from types import SimpleNamespace

    return SimpleNamespace(status="failed", reply=None, handled=False, should_handoff_to_ai=False)


def _try_process_flow_message(company_id, chatbot_id, message, customer_id, source_channel):
    try:
        from app.services.flow_executor_service import process_flow_message
    except ImportError as exc:
        logging.exception("Flow executor import failed for chatbot %s: %s", chatbot_id, exc)
        return _flow_runtime_failed_result()

    try:
        return process_flow_message(company_id, chatbot_id, message, str(customer_id), source_channel=source_channel)
    except Exception as exc:
        logging.exception("Flow executor runtime failed for chatbot %s: %s", chatbot_id, exc)
        return _flow_runtime_failed_result()

def _usd_to_micro_usd(raw_cost) -> int | None:
    """Convert a USD cost value to integer micro-USD using Decimal arithmetic.

    Args:
        raw_cost: The cost value from the provider response (str, int, float, Decimal, or None).

    Returns:
        int: Positive micro-USD value.
        None: When cost is missing, invalid, or negative.

    Never silently converts unknown/missing cost to zero.
    """
    if raw_cost is None:
        return None
    try:
        cost_d = Decimal(str(raw_cost))
    except Exception:
        logging.warning("Invalid provider cost value: %r", raw_cost)
        return None

    if cost_d < 0:
        logging.warning("Negative provider cost value: %s", cost_d)
        return None

    if cost_d == 0:
        return 0

    # Convert to micro-USD with explicit rounding
    micro = (cost_d * Decimal("1_000_000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(micro)


ERROR_REPLY_PATTERNS = [
    "encountered an error while processing your request",
    "having trouble replying right now",
    "having trouble connecting",
    "not sure how to answer that right now",
]


# Recognised AI operation types for usage logging.
# Extend this set when adding new AI operation paths.
OPERATION_CHAT_REPLY = "chat_reply"
OPERATION_TEST_CHAT = "test_chat"
OPERATION_TEST_BOT = "test_bot"
OPERATION_AI_REPORT = "ai_report"
OPERATION_WELCOME_MENU = "welcome_menu_generation"
OPERATION_TEST_SCENARIO_GENERATION = "test_scenario_generation"
OPERATION_PERSONA_DERIVATION = "persona_derivation"
OPERATION_PROFILE_KNOWLEDGE_MATCH = "profile_knowledge_match"
OPERATION_KNOWLEDGE_REFINEMENT_QUESTIONS = "knowledge_refinement_questions"
OPERATION_KNOWLEDGE_REFINEMENT_VERIFICATION = "knowledge_refinement_verification"
OPERATION_WEBSITE_KNOWLEDGE_EXTRACTION = "website_knowledge_extraction"
OPERATION_KNOWLEDGE_GRAPH_EXTRACTION = "knowledge_graph_extraction"

from app.database.knowledge_file_repository import get_active_knowledge_file
from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
OPERATION_KNOWLEDGE_EXTRACTION = "knowledge_extraction"


@dataclass
class _ProviderResult:
    """Internal structured result from a single AI provider call.

    The router uses this inside its provider-calling layer so that
    usage metadata can be captured for billing. External callers
    still receive a plain text string.

    Attributes:
        text: The generated response text (or error text).
        success: True when the provider returned a usable response.
        provider: The provider identifier (e.g. "openai", "deepseek").
        model: The model identifier (e.g. "openai/gpt-5.5").
        prompt_tokens: Prompt token count (0 if unknown).
        completion_tokens: Completion token count (0 if unknown).
        total_tokens: Total tokens (0 if unknown).
        reasoning_tokens: Reasoning tokens (0 if unknown/not available).
        cached_tokens: Cached tokens (0 if unknown/not available).
        provider_cost_micro_usd: Provider cost in micro-USD, or None if unknown.
        generation_id: OpenRouter generation ID for deduplication (None if unknown).
        request_status: "completed" or "failed".
    """
    text: str
    success: bool = True
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    provider_cost_micro_usd: int | None = None
    generation_id: str | None = None
    request_status: str = "completed"
    is_provider_response: bool = False
    billing_fx_rate_micro_myr_per_usd: int | None = None
    billing_markup_basis_points: int | None = None


def _should_log_provider_usage(result) -> bool:
    """Safely determine whether a _ProviderResult represents genuine provider usage.

    Uses getattr for runtime safety: if an unexpected object without the
    is_provider_response attribute reaches this check, it is treated as
    non-billable (returns False).
    """
    return bool(getattr(result, "is_provider_response", False))



def _extract_openrouter_usage(data: dict, provider: str, model: str) -> dict:
    """Extract usage metadata from an OpenRouter (OpenAI-compatible) JSON response.

    Returns a dict compatible with _ProviderResult fields.
    OpenRouter may or may not include usage and cost in the response.
    When cost is present, it is converted from decimal USD to integer micro-USD.
    """
    usage = data.get("usage") or {}
    raw_cost = usage.get("cost") if isinstance(usage, dict) else None
    cost_micro = _usd_to_micro_usd(raw_cost)

    return {
        "provider": provider,
        "model": data.get("model", model),
        "prompt_tokens": usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0,
        "completion_tokens": usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0,
        "total_tokens": usage.get("total_tokens", 0) if isinstance(usage, dict) else 0,
        "reasoning_tokens": usage.get("reasoning_tokens", 0) if isinstance(usage, dict) else 0,
        "provider_cost_micro_usd": cost_micro,
        "generation_id": data.get("id"),
    }



_SUPPORTED_DEEPSEEK_MODELS = frozenset({"deepseek-v4-flash"})

_DEEPSEEK_CACHE_HIT_INPUT_PRICE_ENV = "DEEPSEEK_V4_FLASH_CACHE_HIT_INPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS"
_DEEPSEEK_CACHE_MISS_INPUT_PRICE_ENV = "DEEPSEEK_V4_FLASH_CACHE_MISS_INPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS"
_DEEPSEEK_OUTPUT_PRICE_ENV = "DEEPSEEK_V4_FLASH_OUTPUT_PRICE_MICRO_USD_PER_MILLION_TOKENS"


def _compute_deepseek_provider_cost(
    model: str, prompt_tokens: int, completion_tokens: int, cached_input_tokens: int = 0,
) -> int | None:
    """Calculate provider cost for a system-controlled DeepSeek model.

    Pricing environment variables are in micro-USD per 1,000,000 tokens.
    Cache-hit input, cache-miss input, and output are priced separately.
    Returns integer micro-USD cost, or None when pricing or token information
    is unavailable.

    Arithmetic uses only integer operations -- no float conversions.
    Rounding is always upward (ceil) to avoid undercharging.
    """
    # Normalise cached tokens: invalid or negative -> treat as zero
    if not isinstance(cached_input_tokens, int) or cached_input_tokens < 0:
        cached_input_tokens = 0

    # Clamped: cached tokens cannot exceed total prompt tokens
    if cached_input_tokens > prompt_tokens:
        return None

    uncached_input_tokens = prompt_tokens - cached_input_tokens

    if not uncached_input_tokens and not cached_input_tokens and not completion_tokens:
        return None

    if model not in _SUPPORTED_DEEPSEEK_MODELS:
        return None

    if model == "deepseek-v4-flash":
        cache_hit_env = _DEEPSEEK_CACHE_HIT_INPUT_PRICE_ENV
        cache_miss_env = _DEEPSEEK_CACHE_MISS_INPUT_PRICE_ENV
        output_env = _DEEPSEEK_OUTPUT_PRICE_ENV
    else:
        return None

    import os
    cache_hit_str = os.environ.get(cache_hit_env, "").strip()
    cache_miss_str = os.environ.get(cache_miss_env, "").strip()
    output_str = os.environ.get(output_env, "").strip()

    if not cache_hit_str or not cache_miss_str or not output_str:
        return None

    try:
        cache_hit_rate = int(cache_hit_str)
        cache_miss_rate = int(cache_miss_str)
        output_rate = int(output_str)
    except (ValueError, TypeError):
        return None

    if cache_hit_rate < 0 or cache_miss_rate < 0 or output_rate < 0:
        return None

    numerator = (
        cached_input_tokens * cache_hit_rate
        + uncached_input_tokens * cache_miss_rate
        + completion_tokens * output_rate
    )

    if numerator <= 0:
        return 0 if (cache_hit_rate == 0 and cache_miss_rate == 0 and output_rate == 0) else None

    provider_cost_micro_usd = (numerator + 999999) // 1000000

    if provider_cost_micro_usd < 1:
        provider_cost_micro_usd = 1

    return provider_cost_micro_usd

def _extract_deepseek_usage(response, provider: str, model: str) -> dict:
    """Extract usage metadata from a DeepSeek (OpenAI SDK) response.

    The response is either an OpenAI SDK ChatCompletion object or a JSON dict.
    """
    if hasattr(response, "usage") and response.usage is not None:
        usage = response.usage
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        # Extract cached input tokens from SDK response
        cached = 0
        if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details is not None:
            cached = int(getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0)
        cost = _compute_deepseek_provider_cost(model, pt, ct, cached)
        result = {
            "provider": provider,
            "model": getattr(response, "model", model),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            "provider_cost_micro_usd": cost,
            "generation_id": getattr(response, "id", None),
            "cached_tokens": cached,
        }
        return result
    # Dict fallback for the direct call path
    if isinstance(response, dict):
        usage = response.get("usage") or {}
        pt = int(usage.get("prompt_tokens", 0) or 0)
        ct = int(usage.get("completion_tokens", 0) or 0)
        # Extract cached input tokens from dict response
        cached = 0
        if isinstance(usage, dict):
            details = usage.get("prompt_tokens_details") or {}
            if isinstance(details, dict):
                cached = int(details.get("cached_tokens", 0) or 0)
        cost = _compute_deepseek_provider_cost(model, pt, ct, cached)
        result = {
            "provider": provider,
            "model": response.get("model", model),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "total_tokens": usage.get("total_tokens", 0) or 0,
            "provider_cost_micro_usd": cost,
            "generation_id": response.get("id"),
        }
        if cached:
            result["cached_tokens"] = cached
        return result
    return {"provider": provider, "model": model}


def _extract_gemini_usage(response, provider: str, model: str) -> dict:
    """Extract usage metadata from a Gemini SDK response.

    Gemini returns usage_metadata with token counts but no cost information.
    """
    if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
        meta = response.usage_metadata
        prompt_tokens = getattr(meta, "prompt_token_count", 0) or 0
        completion_tokens = getattr(meta, "candidates_token_count", 0) or 0
        total_tokens = prompt_tokens + completion_tokens
        return {
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "provider_cost_micro_usd": None,
            "generation_id": None,
        }
    return {"provider": provider, "model": model}


def _make_usage_log(result: _ProviderResult, company_id: int, chatbot_id: int, operation_type: str, attempt_number: int) -> dict | None:
    """Write an immutable AI usage log entry and optionally charge AI credit.

    When AI-credit enforcement is enabled, this function also atomically
    charges the logged usage against the company's AI-credit balance.

    Args:
        result: The provider result with usage metadata.
        company_id: The company that owns the chatbot.
        chatbot_id: The chatbot that generated the response.
        operation_type: The type of AI operation.
        attempt_number: The provider-call attempt number.

    Returns:
        The inserted usage-log dictionary, or None if no row was inserted.

    When AI-credit enforcement is enabled, usage-log or charging failure fails
    closed so a customer-billed response is not returned without a debit
    transaction. No second provider call is made.
    """
    try:
        record = insert_usage_log(
            company_id=company_id,
            chatbot_id=chatbot_id,
            provider=result.provider,
            model=result.model,
            operation_type=operation_type,
            request_status=result.request_status,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            reasoning_tokens=result.reasoning_tokens,
            cached_tokens=result.cached_tokens,
            provider_cost_micro_usd=result.provider_cost_micro_usd,
            generation_id=result.generation_id,
            attempt_number=attempt_number,
            billing_fx_rate_micro_myr_per_usd=result.billing_fx_rate_micro_myr_per_usd,
            billing_markup_basis_points=result.billing_markup_basis_points,
        )
    except Exception as exc:
        logging.error(
            "Failed to write AI usage log for company %s chatbot %s: %s",
            company_id, chatbot_id, exc,
        )
        if is_ai_credit_enforcement_enabled():
            raise RuntimeError("AI usage logging failed for a customer-billed request.") from exc
        return None

    if record is None:
        # Duplicate generation_id: lookup existing record for safe re-charging
        if result.generation_id:
            try:
                from app.database.ai_usage_repository import get_usage_log_by_provider_generation_id
                record = get_usage_log_by_provider_generation_id(
                    result.provider, result.generation_id,
                )
            except Exception as exc:
                logging.error(
                    "Failed to lookup existing usage log for provider %s gen %s: %s",
                    result.provider, result.generation_id, exc,
                )
        if record is None:
            if is_ai_credit_enforcement_enabled():
                raise RuntimeError("AI usage logging did not return a chargeable record.")
            return None

    usage_log_id = record.get("id")
    if not usage_log_id:
        if is_ai_credit_enforcement_enabled():
            raise RuntimeError("AI usage log is missing an ID for charging.")
        return None

    if is_ai_credit_enforcement_enabled():
        _charge_logged_usage(usage_log_id, company_id, chatbot_id, operation_type)

    return record




def _charge_logged_usage(usage_log_id: int, company_id: int, chatbot_id: int, operation_type: str):
    """Charge a single AI usage log entry against company AI credit.

    This is called centrally from _make_usage_log when enforcement is enabled.
    It uses the atomic charge RPC to prevent double-charging.

    Charging failure never repeats the provider request, but it does fail
    closed so customer-billed usage is not silently completed without a debit
    transaction.
    """
    try:
        charge_result = charge_logged_ai_usage(
            usage_log_id,
            markup_basis_points=None,
            fx_rate_micro_myr_per_usd=None,
        )
    except Exception as exc:
        logging.error(
            "AI-credit charging failed for usage_log %s (company %s chatbot %s): %s",
            usage_log_id, company_id, chatbot_id, exc,
        )
        raise RuntimeError("AI-credit charging failed.") from exc

    status = charge_result.get("status", "unknown")
    if status == "charged":
        logging.debug(
            "AI credit charged for usage_log %s (company %s)", usage_log_id, company_id,
        )
        _maybe_notify_ai_credit_threshold(charge_result, company_id)
    elif status == "already_charged":
        logging.debug(
            "Usage log %s already charged (idempotent)", usage_log_id,
        )
    elif status == "unknown_cost":
        logging.error(
            "AI-credit charge failed for usage_log %s: provider cost unknown. "
            "Provider response will not be returned to customer.", usage_log_id,
        )
        raise RuntimeError("AI-credit charging failed because provider cost is unknown.")
    elif status == "no_active_subscription":
        logging.error(
            "AI-credit charge failed for usage_log %s: no active subscription "
            "(company %s). Provider response will not be returned.", usage_log_id, company_id,
        )
        raise RuntimeError("AI-credit charging failed because no active subscription exists.")
    elif status == "no_balance":
        logging.error(
            "AI-credit charge failed for usage_log %s: no balance after initialisation "
            "(company %s). Provider response will not be returned.", usage_log_id, company_id,
        )
        raise RuntimeError("AI-credit charging failed because no AI-credit balance exists.")
    elif status == "usage_not_found":
        logging.error(
            "AI-credit charge failed for usage_log %s: usage log not found "
            "immediately after insert (company %s).", usage_log_id, company_id,
        )
        raise RuntimeError("AI-credit charging failed because usage log was not found.")
    else:
        logging.error(
            "AI-credit charge returned unexpected status %r for usage_log %s",
            status, usage_log_id,
        )
        raise RuntimeError("AI-credit charging returned an unexpected status.")


# ---------------------------------------------------------------------------
# Post-charge AI-credit notification helpers
# ---------------------------------------------------------------------------

def _load_notification_thresholds() -> tuple:
    """Load AI-credit notification thresholds from environment with defaults."""
    low = int(os.getenv(
        "AI_CREDIT_LOW_THRESHOLD_MICRO_MYR",
        "5000000",
    ))
    critical = int(os.getenv(
        "AI_CREDIT_CRITICAL_THRESHOLD_MICRO_MYR",
        "1000000",
    ))
    return low, critical


def _determine_trial_status(charge_result: dict) -> bool:
    """Determine whether the charged company is on a Free trial plan.

    Looks up the company's current subscription and checks whether the plan is
    Free. Some repository calls return plan_code directly, while the active
    subscription repository returns plan_id only.
    """
    subscription_id = charge_result.get("subscription_id")
    if not subscription_id:
        return False
    try:
        company_id = charge_result.get("company_id")
        if not company_id:
            return False
        sub = get_company_subscription(int(company_id))
        if not sub:
            return False
        plan_code = (sub.get("plan_code") or "").lower()
        if plan_code:
            return plan_code == "free"
        plan_id = sub.get("plan_id")
        if not plan_id:
            return False
        plan = get_plan_by_id(plan_id)
        if not plan:
            return False
        return (plan.get("code") or "").lower().strip() == "free"
    except Exception:
        logging.warning(
            "Could not determine trial status for subscription %s; "
            "defaulting to paid notification wording.",
            subscription_id,
        )
        return False


def _maybe_notify_ai_credit_threshold(
    charge_result: dict,
    company_id: int,
) -> None:
    """Fire AI-credit threshold notifications after a successful charge.

    Only called when status == 'charged'.  Notification failures are
    caught and logged so they never affect the AI response or undo the
    charge.
    """
    import os
    try:
        included = int(charge_result.get("included_balance_micro_myr") or 0)
        topup = int(charge_result.get("topup_balance_micro_myr") or 0)
        total_balance = included + topup

        low_threshold, critical_threshold = _load_notification_thresholds()

        now = datetime.now(timezone.utc)
        period_key = f"{now.year}-{now.month:02d}"

        is_trial = _determine_trial_status(charge_result)

        if total_balance <= 0:
            notify_ai_credit_depleted(
                company_id=company_id,
                period_key=period_key,
                is_trial=is_trial,
            )
        elif total_balance <= critical_threshold:
            notify_ai_credit_critical(
                company_id=company_id,
                total_balance_micro_myr=total_balance,
                threshold_micro_myr=critical_threshold,
                period_key=period_key,
                is_trial=is_trial,
            )
        elif total_balance <= low_threshold:
            notify_ai_credit_low(
                company_id=company_id,
                total_balance_micro_myr=total_balance,
                threshold_micro_myr=low_threshold,
                period_key=period_key,
                is_trial=is_trial,
            )
    except Exception as exc:
        logging.warning(
            "AI-credit post-charge notification failed for company %s: %s",
            company_id, exc,
        )


def _make_result_from_text(text: str, provider: str = "", model: str = "", success: bool = True) -> _ProviderResult:
    """Wrap an error or direct-reply text into a _ProviderResult."""
    return _ProviderResult(text=text, provider=provider, model=model, success=success)


def _complete_provider_result(text: str, provider: str, model: str, response_data: Any, request_status: str = "completed") -> _ProviderResult:
    """Build a _ProviderResult from a successful provider response.

    Args:
        text: The generated response text.
        provider: Provider identifier.
        model: Model identifier.
        response_data: The raw provider response (dict, SDK object, or None).
        request_status: "completed" or "failed".
    """
    usage = {"provider": provider, "model": model}
    if response_data is not None:
        if isinstance(response_data, dict):
            usage = _extract_openrouter_usage(response_data, provider, model)
        elif hasattr(response_data, "usage"):
            usage = _extract_deepseek_usage(response_data, provider, model)
        elif hasattr(response_data, "usage_metadata"):
            usage = _extract_gemini_usage(response_data, provider, model)
    return _ProviderResult(
        text=text,
        provider=usage.get("provider", provider),
        model=usage.get("model", model),
        prompt_tokens=usage.get("prompt_tokens", 0) or 0,
        completion_tokens=usage.get("completion_tokens", 0) or 0,
        total_tokens=usage.get("total_tokens", 0) or 0,
        reasoning_tokens=usage.get("reasoning_tokens", 0) or 0,
        cached_tokens=usage.get("cached_tokens", 0) or 0,
        provider_cost_micro_usd=usage.get("provider_cost_micro_usd"),
        generation_id=usage.get("generation_id"),
        request_status=request_status,
        is_provider_response=True,
    )




def _validate_deepseek_pricing_config():
    """Validate that DeepSeek Flash pricing is configured.

    Raises RuntimeError if pricing is incomplete or invalid.
    This is a server-side configuration error, not a customer-facing error.
    """
    import os

    env_names = (
        _DEEPSEEK_CACHE_HIT_INPUT_PRICE_ENV,
        _DEEPSEEK_CACHE_MISS_INPUT_PRICE_ENV,
        _DEEPSEEK_OUTPUT_PRICE_ENV,
    )
    for env_name in env_names:
        val = os.environ.get(env_name, "").strip()
        if not val:
            raise RuntimeError(
                f"AI-credit enforcement requires {env_name} to be set. "
                "Configure DeepSeek model pricing before enabling enforcement."
            )
        try:
            rate = int(val)
        except (ValueError, TypeError):
            raise RuntimeError(
                f"AI-credit enforcement: {env_name}={val!r} is not a valid integer. "
                "Configure DeepSeek model pricing before enabling enforcement."
            )
        if rate < 0:
            raise RuntimeError(
                f"AI-credit enforcement: {env_name}={val!r} must be a non-negative integer. "
                "Configure DeepSeek model pricing before enabling enforcement."
            )



def _is_free_plan_company(company_id: int) -> bool:
    """Check whether a company is on the Free trial plan.

    Looks up the subscription, resolves plan_id to plan code via
    get_plan_by_id, and checks whether the code is "free".
    Uses the same pattern as ai_access_policy.resolve_ai_access().
    Defaults to False (paid wording) when lookup fails.
    """
    try:
        sub = get_company_subscription(int(company_id))
        if not sub:
            return False
        plan_id = sub.get("plan_id")
        if not plan_id:
            return False
        plan = get_plan_by_id(plan_id)
        if not plan:
            return False
        plan_code = (plan.get("code") or "").lower().strip()
        return plan_code == "free"
    except Exception:
        logging.warning(
            "Could not determine plan for company %s; defaulting to paid wording.",
            company_id,
        )
        return False


def _check_ai_credit_before_provider(company_id: int | None):
    if not is_ai_credit_enforcement_enabled():
        return

    if not company_id:
        raise RuntimeError(
            "AI-credit enforcement requires a valid company_id, got None."
        )

    get_ai_retail_markup_basis_points()
    get_ai_usd_to_myr_rate_micro_myr_per_usd()

    summary = get_company_ai_credit_summary(company_id)

    # Lazy initialisation: if no balance row exists, attempt to create one.
    # This handles companies created before AI-credit support,
    # partial registration failures, and missing balance rows.
    # Idempotent: ensure_company_ai_credit is safe to call when already initialised.
    if not summary.get("initialised"):
        ensure_company_ai_credit(company_id)
        summary = get_company_ai_credit_summary(company_id)
        if not summary.get("initialised"):
            raise RuntimeError(
                f"AI-credit period has not been initialised for company {company_id}. "
                f"If this is an active paid subscription, a callback or reconciliation "
                f"should have completed activation. Manual reconciliation may be required."
            )


    total = summary.get("total_balance_micro_myr")
    if total is None or not isinstance(total, int):
        raise RuntimeError(
            f"AI-credit total_balance_micro_myr is invalid for company {company_id}: {total!r}."
        )

    if total <= 0:
        try:
            is_free = _is_free_plan_company(company_id)
        except Exception:
            logging.warning(
                "Failed to determine plan for company %s; defaulting to paid wording.",
                company_id,
            )
            is_free = False
        if is_free:
            raise BillingLimitError(
                "Your trial AI credit has been fully used. Please upgrade to a paid plan to continue.",
                code="ai_credit_insufficient",
            )
        raise BillingLimitError(
            "Your account has no remaining AI credit. Please top up to continue.",
            code="ai_credit_insufficient",
        )


def _route_for_enforcement(provider: str, model: str | None, company_id: int | None = None):
    # Resolve AI access policy.
    # The company_id must be available from the calling context (set in g) or passed directly.
    if not company_id:
        from flask import g, has_app_context
        company_id = getattr(g, "company_id", None) if has_app_context() else None
        
    if not company_id:
        raise RuntimeError("No company context available for routing enforcement.")

    policy = resolve_ai_access(company_id)

    if not policy.allowed:
        raise BillingLimitError(
            policy.denial_reason or "AI access is not available on your current plan.",
            code="ai_access_denied",
        )

    if policy.api_route == ROUTE_DIRECT_DEEPSEEK:
        # Trial: only direct DeepSeek allowed
        if provider != TRIAL_PROVIDER:
            raise BillingLimitError(
                "During your trial period, only the DeepSeek AI provider is available.",
                code="trial_provider_restricted",
            )
        # Force the fixed trial model
        # Validate DeepSeek Flash pricing is configured before allowing the call
        _validate_deepseek_pricing_config()

        return TRIAL_PROVIDER, TRIAL_MODEL

    if policy.api_route == ROUTE_OPENROUTER:
        # Paid: reject direct DeepSeek
        if provider not in OPENROUTER_PROVIDER_FAMILIES:
            raise BillingLimitError(
                "The selected AI provider is not available on your plan.",
                code="provider_not_available",
            )
        # Validate model against plan tier at runtime
        if not model:
            raise BillingLimitError(
                "No model specified for the request.",
                code="model_missing",
            )
        if not is_openrouter_model(model):
            raise BillingLimitError(
                "The specified model is not an approved OpenRouter model.",
                code="model_not_openrouter",
            )
        if not is_model_allowed_for_tier(model, policy.max_model_tier):
            raise BillingLimitError(
                "The selected model is not available on your plan. "
                "Please choose a model within your plan's allowed tier.",
                code="model_tier_denied",
            )
        # Validate provider-model pair
        if get_model_provider(model) != provider:
            raise BillingLimitError(
                f"Model '{model}' is not valid for provider '{provider}'.",
                code="provider_model_mismatch",
            )
        return provider, model

    # Fall-closed
    raise BillingLimitError(
        policy.denial_reason or "AI access is not available.",
        code="ai_access_denied",
    )


def _get_system_provider_for_enforcement(provider: str, model: str | None, company_id: int):
    # Resolve AI access policy.
    # System callers (report_service, flow_builder_service, knowledge_service)
    # resolve the company_id from the bot record before calling.
    from app.services.ai_access_policy import resolve_ai_access

    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        raise RuntimeError("A valid company context is required for system AI routing enforcement.")

    policy = resolve_ai_access(company_id)

    if not policy.allowed:
        raise BillingLimitError(
            policy.denial_reason or "AI access is not available on your current plan.",
            code="ai_access_denied",
        )

    if policy.api_route == ROUTE_DIRECT_DEEPSEEK:
        if provider != TRIAL_PROVIDER:
            raise BillingLimitError(
                "During your trial period, only the DeepSeek AI provider is available.",
                code="trial_provider_restricted",
            )
        # Validate DeepSeek Flash pricing is configured before allowing the call
        _validate_deepseek_pricing_config()

        return TRIAL_PROVIDER, TRIAL_MODEL

    if policy.api_route == ROUTE_OPENROUTER:
        if provider not in OPENROUTER_PROVIDER_FAMILIES:
            raise BillingLimitError(
                "The selected AI provider is not available on your plan.",
                code="provider_not_available",
            )
        # Validate model against plan tier at runtime (system calls)
        if not model:
            raise BillingLimitError(
                "No model specified for the system request.",
                code="model_missing",
            )
        if not is_openrouter_model(model):
            raise BillingLimitError(
                "The specified model is not an approved OpenRouter model.",
                code="model_not_openrouter",
            )
        if not is_model_allowed_for_tier(model, policy.max_model_tier):
            raise BillingLimitError(
                "The selected model is not available on your plan. "
                "Please choose a model within your plan's allowed tier.",
                code="model_tier_denied",
            )
        # Validate provider-model pair
        if get_model_provider(model) != provider:
            raise BillingLimitError(
                f"Model '{model}' is not valid for provider '{provider}'.",
                code="provider_model_mismatch",
            )
        return provider, model

    raise BillingLimitError(
        policy.denial_reason or "AI access is not available.",
        code="ai_access_denied",
    )


def is_error_reply(reply):
    if not reply:
        return True

    reply_lower = reply.lower()
    return any(pattern in reply_lower for pattern in ERROR_REPLY_PATTERNS)


def call_provider(
    provider,
    message,
    customer_id,
    chatbot_id,
    model_name=None,
    temperature=0.7,
    source_channel="whatsapp",
    company_id=None,
):
    """Call an AI provider and return a _ProviderResult with usage metadata.

    This is the internal provider-calling layer. External callers always
    receive a plain string through generate_response().
    """
    provider = provider.lower().strip()

    if provider in OPENROUTER_PROVIDER_KEYS:
        # Run an early credit preflight for non-local requests.
        # Local intents (greeting, main_menu, out_of_scope) return a direct
        # reply before embedding or generation. Check credit only when a
        # text-generation provider call would actually be needed, so that
        # free local responses never trigger a credit check.
        from app.services.chat_logic_service import detect_intent

        preflight_intent = detect_intent(message)
        if preflight_intent not in ("greeting", "main_menu", "out_of_scope"):
            _check_ai_credit_before_provider(company_id)

        pipeline = prepare_chat_prompt(
            message=message,
            customer_id=customer_id,
            chatbot_id=chatbot_id,
            source_channel=source_channel,
        )

        if pipeline.get("direct_reply"):
            return _make_result_from_text(pipeline["direct_reply"], provider)

        prompt = pipeline.get("prompt")

        if not prompt:
            raise ValueError("Prompt could not be prepared for OpenRouter provider.")

        model = model_name if model_name else get_default_model(provider)

        if not model:
            raise ValueError(f"No default model found for provider: {provider}")

        _check_ai_credit_before_provider(company_id)

        success, raw = openrouter_service._request(
            prompt=prompt,
            model=model,
            temperature=temperature,
        )

        if not success:
            return _make_result_from_text(raw, provider, model, success=False)

        data = raw
        text = data["choices"][0]["message"]["content"].strip()
        return _complete_provider_result(text, "openrouter", model, data)

    if provider == "deepseek":
        model = model_name if model_name else get_default_model("deepseek")

        _check_ai_credit_before_provider(company_id)

        success, raw = deepseek_service._request(
            message,
            customer_id,
            chatbot_id,
            model=model,
            temperature=temperature,
            source_channel=source_channel,
        )

        if not success:
            return _make_result_from_text(raw, provider, model, success=False)

        if isinstance(raw, dict) and "choices" in raw:
            text = raw["choices"][0]["message"]["content"].strip()
            return _make_result_from_text(text, provider, model)

        if hasattr(raw, "choices"):
            reply = raw.choices[0].message.content
            if reply:
                text = reply.strip()
                return _complete_provider_result(text, "deepseek", model, raw)
            return _make_result_from_text("Sorry, I'm not sure how to answer that right now.", provider, model)

        return _make_result_from_text(str(raw), provider, model)

    raise ValueError(f"Unsupported AI provider: {provider}")


def generate_response(message, customer_id, chatbot_id, source_channel="whatsapp", operation_type=OPERATION_CHAT_REPLY):
    """Generate a response using the appropriate AI provider..."""

    # Enforce billing usage logging...
    from app.services.ai_credit_service import is_ai_credit_enforcement_enabled
    from app.services.company_status_service import ensure_company_operational
    try:

        bot = get_bot_by_id(chatbot_id)

        if not bot:
            logging.warning(
                "Bot %s not found. AI response denied - no provider configuration available.",
                chatbot_id,
            )
            return "Sorry, I'm having trouble replying right now. Please try again later."

        selected_provider = bot.get("ai_provider", "deepseek")
        model_name = bot.get("model_name")
        temperature = bot.get("temperature", 0.7)
        company_id = bot.get("company_id")
        ensure_company_operational(company_id)

        flow_result = _try_process_flow_message(company_id, chatbot_id, message, customer_id, source_channel)
        if flow_result.handled:
            logging.info("Flow Builder handled message for bot %s.", chatbot_id)
            return flow_result.reply
        if not flow_result.should_handoff_to_ai:
            logging.error(
                "Flow Builder runtime failed for company %s chatbot %s; returning safe fallback.",
                company_id,
                chatbot_id,
            )
            return FLOW_RUNTIME_FAILURE_REPLY

        selected_provider, model_name = normalize_model_selection(
            selected_provider,
            model_name,
        )

        selected_provider, model_name = _route_for_enforcement(selected_provider, model_name, company_id)

        logging.info(
            f"Routing request for Bot {chatbot_id} to provider: {selected_provider}, model: {model_name}"
        )

        try:
            result = call_provider(
                selected_provider,
                message,
                customer_id,
                chatbot_id,
                model_name=model_name,
                temperature=temperature,
                source_channel=source_channel,
                company_id=company_id,
            )

            if _should_log_provider_usage(result) and company_id:
                _make_usage_log(result, company_id, chatbot_id, operation_type, attempt_number=1)

            if not is_error_reply(result.text):
                return clean_ai_reply(result.text)

            logging.warning(
                "Provider %s returned an error reply. Cross-provider fallback is disabled.",
                selected_provider,
            )

        except BillingLimitError:
            raise
        except Exception as provider_error:
            logging.error(
                "Provider %s failed: %s. Cross-provider fallback is disabled.",
                selected_provider,
                provider_error,
            )

        return "Sorry, I'm having trouble replying right now. Please try again later."

    except BillingLimitError:
        raise
    except Exception as e:
        logging.error(f"AI Router Error: {e}")
        return "Sorry, I'm having trouble replying right now. Please try again later."


def _call_deepseek_direct(prompt, model, temperature, json_response=False, stream=False):
    """Call Deepseek directly with a plain prompt.

    Returns a _ProviderResult with the generated text and usage metadata,
    or the stream iterator if stream=True.
    """
    from openai import OpenAI
    import os

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is missing.")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    kwargs = {
        "model": model or "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "stream": stream,
    }
    if json_response:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    
    if stream:
        return response

    reply = response.choices[0].message.content
    if reply:
        text = reply.strip()
        return _complete_provider_result(text, "deepseek", model or "deepseek-chat", response)
    raise RuntimeError("DeepSeek returned an empty response.")





def _call_openrouter_direct(prompt, model, temperature):
    """Call OpenRouter directly with a plain prompt (no chat pipeline).

    Returns a _ProviderResult with the generated text and usage metadata.
    """
    import os
    import requests

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is missing.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-OpenRouter-Title": "AI Chatbot System",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"].strip()
    return _complete_provider_result(text, "openrouter", model, data)


def generate_system_response(prompt, chatbot_id, provider=None, model=None, temperature=None, json_response=False, operation_type=OPERATION_KNOWLEDGE_EXTRACTION):
    """Generate an AI response for system/background tasks (non-chat).

    This is the ONLY authorized function for system AI calls. It enforces
    billing limits centrally.

    Args:
        prompt: The prompt string to send to the LLM
        chatbot_id: The chatbot ID (for billing check and provider lookup)
        provider: Optional provider override (defaults to bot's provider)
        model: Optional model override (defaults to bot's model)
        temperature: Optional temperature override (defaults to 0.3 for system)
        json_response: Whether to request JSON mode (DeepSeek supports this natively)

    Returns:
        The LLM response text, or raises RuntimeError on failure
    """

    from app.services.company_status_service import ensure_company_operational

    bot = get_bot_by_id(chatbot_id)
    if not bot:
        logging.warning(
            "System AI call denied for chatbot %s because the bot record was not found.",
            chatbot_id,
        )
        raise RuntimeError("Chatbot is not available for system AI.")

    company_id = bot.get("company_id")
    ensure_company_operational(company_id)

    selected_provider = provider or bot.get("ai_provider", "deepseek")
    selected_model = model or bot.get("model_name")
    selected_temperature = temperature if temperature is not None else bot.get("temperature", 0.3)

    selected_provider, selected_model = normalize_model_selection(
        selected_provider,
        selected_model,
    )

    if not selected_model:
        selected_model = get_default_model(selected_provider)

    selected_provider, selected_model = _get_system_provider_for_enforcement(
        selected_provider, selected_model, company_id,
    )

    logging.info(
        "System AI call for chatbot %s -> provider: %s, model: %s",
        chatbot_id, selected_provider, selected_model,
    )

    company_id = bot.get("company_id") if bot else None

    result = None

    if selected_provider == "deepseek":
        _check_ai_credit_before_provider(company_id)
        result = _call_deepseek_direct(prompt, selected_model, selected_temperature, json_response)
    elif selected_provider in OPENROUTER_PROVIDER_KEYS:
        _check_ai_credit_before_provider(company_id)
        result = _call_openrouter_direct(prompt, selected_model, selected_temperature)
    else:
        logging.warning("Unsupported system AI provider: %s (fail-closed)", selected_provider)
        raise RuntimeError(f"Unsupported AI provider: {selected_provider}. This path should not be reached because _get_system_provider_for_enforcement already validates permitted providers.")

    if result and _should_log_provider_usage(result) and company_id:
        _make_usage_log(result, company_id, chatbot_id, operation_type, attempt_number=1)

    return result.text if result else "Sorry, an error occurred generating the response."

def generate_welcome_menu_suggestions(chatbot_id: int, company_id: int):
    active_pdf = get_active_knowledge_file(chatbot_id)
    if not active_pdf:
        raise ValueError("No active document found. Please upload and activate a document first.")

    file_id = active_pdf.get("id")
    file_name = active_pdf.get("file_name", "Unknown document")
    if not file_id:
        raise ValueError("Active document is missing an ID.")

    chunks = get_chunks_by_file_for_chatbot(chatbot_id, file_id)
    if not chunks:
        raise ValueError("The active document has no text content to analyze.")

    content = "\n\n".join([chunk.get("content", "") for chunk in chunks])

    # Take up to 20,000 characters to avoid exceeding context window
    content = content[:20000]

    prompt = f"""You are an AI generating a welcome menu for a chatbot.
Based on the following knowledge document, extract up to 8 short topics that are highly relevant to users and would make excellent persistent main menu buttons.

Rules:
1. Each button label MUST be less than 20 characters long.
2. Each description MUST be less than 60 characters long.
3. Return ONLY a JSON array of objects, each with "label" and "description" keys.
4. Do not include markdown blocks, just the raw JSON array.

Example response:
[{{"label": "Pricing", "description": "View our pricing plans and packages"}}, {{"label": "Our Services", "description": "See what services we offer"}}, {{"label": "Contact Us", "description": "Get in touch with our team"}}]

Document Content:
{content}
"""

    try:
        import json
        response = generate_system_response(
            prompt=prompt,
            chatbot_id=chatbot_id,
            operation_type=OPERATION_WELCOME_MENU,
            json_response=True,
        )
        # Parse the response as JSON
        if not response:
            return [], file_name

        # Clean any accidental markdown from the response
        clean_res = response.strip()
        if clean_res.startswith("```json"):
            clean_res = clean_res[7:]
        if clean_res.startswith("```"):
            clean_res = clean_res[3:]
        if clean_res.endswith("```"):
            clean_res = clean_res[:-3]

        parsed = json.loads(clean_res.strip())

        if isinstance(parsed, list):
            result = []
            for item in parsed[:8]:
                if isinstance(item, dict):
                    label = str(item.get("label", ""))[:20]
                    description = str(item.get("description", ""))[:60]
                    if label:
                        result.append({"label": label, "description": description})
                elif isinstance(item, str):
                    # Backward-compatible fallback: bare string labels
                    if item:
                        result.append({"label": item[:20], "description": ""})
            return result, file_name

        return [], file_name

    except Exception as e:
        logging.error("Failed to generate welcome menu suggestions: %s", e)
        return [], file_name
