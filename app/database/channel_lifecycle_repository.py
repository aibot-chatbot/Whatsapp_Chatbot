"""The database transaction is the authority for connection replacement."""

from app.database.db import supabase


PROVIDER_TABLES = {
    "telegram": "telegram_channels",
    "whatsapp": "whatsapp_channels",
    "wasender": "wasender_channels",
}


class ChannelActivationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _table(provider):
    if provider not in PROVIDER_TABLES:
        raise ValueError("Unsupported channel provider")
    return PROVIDER_TABLES[provider]


def get_channel_by_id(provider, channel_id):
    response = supabase.table(_table(provider)).select("*").eq("id", channel_id).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


def ensure_channel_slot(provider, chatbot_id, company_id):
    # This early check avoids unnecessary provider setup. The RPC repeats the
    # count inside the company lock; the early check is not the concurrency gate.
    from app.services.billing_guard import can_connect_channel

    response = (supabase.table(_table(provider)).select("id")
                .eq("chatbot_id", chatbot_id).eq("company_id", company_id)
                .eq("is_active", True).eq("connection_status", "connected")
                .limit(1).execute())
    if not response.data:
        can_connect_channel(company_id)


def activate_channel(provider, channel_id, chatbot_id, company_id, *, expected_attempt_at=None):
    _table(provider)
    # Reuse the billing engine's expiry/grace rules. Only the service role can
    # invoke this RPC, so limits can never be supplied by a browser caller.
    from app.services.billing_guard import _resolve_company_subscription

    subscription = _resolve_company_subscription(company_id)
    if not subscription or not isinstance(subscription.get("plan"), dict):
        raise ChannelActivationError("no_subscription", "An active subscription is required to connect a channel.")
    limit = subscription["plan"].get("channel_limit")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
        raise ChannelActivationError("usage_unavailable", "Unable to verify the channel limit. Please retry.")
    try:
        response = supabase.rpc("activate_verified_channel", {
            "p_provider": provider,
            "p_channel_id": channel_id,
            "p_chatbot_id": chatbot_id,
            "p_company_id": company_id,
            "p_channel_limit": limit,
            "p_expected_attempt_at": expected_attempt_at,
        }).execute()
    except Exception as exc:
        if "channel_limit_reached" in str(exc):
            raise ChannelActivationError("channel_limit", "Your plan's channel limit has been reached.") from exc
        raise ChannelActivationError("activation_unavailable", "Could not finish the connection. Please retry.") from exc
    data = response.data
    if data is None:
        return None
    if not isinstance(data, dict) or not data.get("id"):
        raise ChannelActivationError("activation_unavailable", "Could not finish the connection. Please retry.")
    return data
