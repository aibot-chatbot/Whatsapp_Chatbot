"""Read provider identity and delivery configuration before switching channels."""

import os
import re

import requests

# Graph pages are 100 numbers each; 10 pages is far past any real account.
MAX_PROVIDER_PAGES = 10


def normalize_phone_number(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"\+?[0-9 ()-]+", value):
        raise ValueError("Enter a phone number with its country code.")
    digits = re.sub(r"[^0-9]", "", value)
    if not 7 <= len(digits) <= 15 or digits.startswith("0"):
        raise ValueError("Enter a phone number with its country code.")
    return "+" + digits


def _provider_get(url, token, params=None):
    if not token:
        raise ValueError("Provider credentials are missing. Authorize this connection again.")
    response = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                            params=params, timeout=15)
    if response.status_code >= 500 or response.status_code == 429:
        # The provider is unwell, the credentials are not wrong. Callers map
        # RequestException to "unable to verify, previous connection unchanged"
        # (502); a ValueError here would instead mark a brand-new connection
        # permanently failed and tell the tenant to redo Embedded Signup because
        # Meta had a bad two seconds.
        raise requests.RequestException(
            f"Provider verification is temporarily unavailable (HTTP {response.status_code})."
        )
    if response.status_code != 200:
        raise ValueError("Provider verification failed. Check the credentials and account permissions.")
    data = response.json()
    if not isinstance(data, dict) or data.get("success") is False or data.get("error"):
        raise ValueError("Provider returned an unsuccessful verification response.")
    return data


def verify_meta_connection(phone_number_id, waba_id, access_token, expected_phone=None):
    app_id = (os.getenv("WHATSAPP_META_APP_ID") or "").strip()
    app_secret = os.getenv("WHATSAPP_META_APP_SECRET")
    public_base_url = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if not app_id or not app_secret or not public_base_url:
        raise ValueError("Meta app credentials and public webhook URL must be configured on the server.")
    version = os.getenv("WHATSAPP_GRAPH_API_VERSION") or os.getenv("VERSION") or "v22.0"
    base = f"https://graph.facebook.com/{version}"
    params = {"fields": "id,display_phone_number,verified_name,quality_rating,code_verification_status", "limit": 100}
    phone = None
    seen_cursors = set()
    # Each page costs up to 15s and this runs inside a request handler that
    # gunicorn kills at 120s, so the repeated-cursor guard alone is not a bound.
    for _ in range(MAX_PROVIDER_PAGES):
        payload = _provider_get(f"{base}/{waba_id}/phone_numbers", access_token, params)
        phone = next((item for item in payload.get("data", [])
                      if isinstance(item, dict) and str(item.get("id")) == str(phone_number_id)), None)
        if phone:
            break
        paging = payload.get("paging") or {}
        cursor = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
        if not cursor or cursor in seen_cursors:
            raise ValueError("The selected phone number does not belong to this WhatsApp Business Account.")
        seen_cursors.add(cursor)
        params["after"] = cursor
    else:
        raise ValueError("This WhatsApp Business Account has too many numbers to search. "
                         "Enter the phone number ID directly.")

    actual_phone = normalize_phone_number(phone.get("display_phone_number"))
    if expected_phone and actual_phone != normalize_phone_number(expected_phone):
        raise ValueError("The authorized Meta phone number does not match the requested new number.")
    if phone.get("code_verification_status") not in (None, "VERIFIED"):
        raise ValueError("Complete phone-number verification in Meta before connecting.")
    subscription = _provider_get(f"{base}/{waba_id}/subscribed_apps", access_token)
    waba_apps = subscription.get("data")
    if not isinstance(waba_apps, list):
        raise ValueError("Meta did not return verifiable WhatsApp app subscriptions.")
    matching_apps = []
    for item in waba_apps:
        if not isinstance(item, dict):
            raise ValueError("Meta did not return verifiable WhatsApp app subscriptions.")
        app = item.get("whatsapp_business_api_data", item)
        if not isinstance(app, dict):
            raise ValueError("Meta did not return verifiable WhatsApp app subscriptions.")
        if str(app.get("id")) == app_id:
            matching_apps.append(item)
    if len(matching_apps) != 1:
        raise ValueError("Subscribe this WhatsApp Business Account to the configured Meta app before connecting.")

    # This app-level read requires the server's app token, not the customer's token.
    subscriptions = _provider_get(f"{base}/{app_id}/subscriptions", f"{app_id}|{app_secret}").get("data")
    if not isinstance(subscriptions, list) or any(not isinstance(item, dict) for item in subscriptions):
        raise ValueError("Meta did not return a verifiable webhook configuration.")
    matching_subscriptions = [item for item in subscriptions if item.get("object") == "whatsapp_business_account"]
    if len(matching_subscriptions) != 1:
        raise ValueError("Configure one WhatsApp Business Account webhook subscription in the Meta app.")
    webhook = matching_subscriptions[0]
    fields = webhook.get("fields")
    if (webhook.get("active") is not True or not isinstance(fields, list)
            or not any((field.get("name") if isinstance(field, dict) else field) == "messages" for field in fields)):
        raise ValueError("Enable the messages webhook subscription in the Meta app before connecting.")
    # WABA overrides take precedence over the app's default for messages notifications.
    override = matching_apps[0].get("override_callback_uri")
    if override is not None and not isinstance(override, str):
        raise ValueError("Meta did not return a verifiable webhook callback URL.")
    callback = override or webhook.get("callback_url")
    if callback != f"{public_base_url}/webhook":
        raise ValueError("The Meta messages webhook callback does not match this server. Update it before connecting.")
    return phone


def verify_wasender_connection(channel, personal_access_token=None):
    base = os.getenv("WASENDER_BASE_URL", "https://wasenderapi.com").rstrip("/")
    api_key = channel.get("api_key")
    status = _provider_get(f"{base}/api/status", api_key).get("status")
    if status != "connected":
        return {"verified": False, "next_action": "pair_session", "delivery_status": "pending",
                "message": "Pair the new number in WasenderAPI, then verify again."}

    user = _provider_get(f"{base}/api/user", api_key).get("data") or {}
    jid = str(user.get("id") or "")
    if not re.fullmatch(r"[0-9]+(?::[0-9]+)?@s\.whatsapp\.net", jid):
        raise ValueError("WasenderAPI did not return a verifiable phone identity.")
    actual_phone = normalize_phone_number(jid.split("@")[0].split(":")[0])
    if actual_phone != normalize_phone_number(channel.get("phone_number")):
        raise ValueError("The paired WasenderAPI number does not match the requested new number.")
    result = {"provider_user_id": actual_phone, "verified": False,
              "next_action": "configure_webhook", "delivery_status": "pending",
              "message": "Configure this webhook in WasenderAPI, then verify with the session ID and personal access token."}
    if not personal_access_token or not channel.get("session_id"):
        return result
    session_id = str(channel["session_id"])
    if not session_id.isdigit():
        raise ValueError("WasenderAPI session ID must be numeric.")
    session = _provider_get(f"{base}/api/whatsapp-sessions/{session_id}", personal_access_token).get("data") or {}
    if str(session.get("id")) != session_id or session.get("api_key") != api_key:
        raise ValueError("The WasenderAPI session does not match the supplied API key.")
    if (session.get("status") != "connected"
            or normalize_phone_number(session.get("phone_number")) != actual_phone):
        raise ValueError("The WasenderAPI session is not paired with the requested number.")
    if (session.get("webhook_url") != channel.get("webhook_url")
            or session.get("webhook_enabled") is not True
            or "messages.received" not in (session.get("webhook_events") or [])):
        return result
    return {"provider_user_id": actual_phone, "verified": True, "next_action": None,
            "delivery_status": "connected", "message": "Session identity and webhook configuration verified."}
