"""HTTP client for the WhatChimp WhatsApp API (app.whatchimp.com/api/v1).

Every call posts form fields with the account's apiToken in the body, never the
URL, so the key stays out of access logs. Calls return {"success", "data",
"error"} like the WaSender client, so callers can persist failures the same way.
"""

import json
import logging
import os
import re

import requests

WHATCHIMP_BASE_URL = os.getenv("WHATCHIMP_BASE_URL", "https://app.whatchimp.com")
REQUEST_TIMEOUT_SECONDS = 20
# Same limits as the official WhatsApp channel: WhatChimp numbers run on the Cloud API.
MAX_REPLY_BUTTONS = 3
MAX_BUTTON_TITLE_LENGTH = 20


def whatchimp_recipient(value) -> str:
    """WhatChimp wants the country code and digits only: '+60 12-345 6789' -> '60123456789'."""
    return re.sub(r"\D", "", str(value or "").split("@", 1)[0])


def _post(path: str, fields: dict) -> dict:
    url = f"{WHATCHIMP_BASE_URL.rstrip('/')}/api/v1/{path}"
    try:
        # No redirects: requests would re-send the form body, API key included, to the new host.
        response = requests.post(url, data=fields, headers={"Accept": "application/json"},
                                 timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)
    except requests.Timeout:
        logging.warning("WhatChimp request timed out: %s", path)
        return {"success": False, "data": None, "error": "WhatChimp did not answer in time"}
    except requests.RequestException as exc:
        logging.warning("WhatChimp request failed: %s (%s)", path, type(exc).__name__)
        return {"success": False, "data": None, "error": "Could not reach WhatChimp"}

    try:
        data = response.json()
    except ValueError:
        data = None
    # WhatChimp signals success with status "1" (a string) in the JSON body.
    if response.status_code < 400 and isinstance(data, dict) and str(data.get("status")) == "1":
        return {"success": True, "data": data, "error": None}

    reason = data.get("message") if isinstance(data, dict) else None
    logging.warning("WhatChimp %s was rejected: HTTP %s", path, response.status_code)
    return {
        "success": False,
        "data": data,
        "error": reason if isinstance(reason, str) and reason else f"WhatChimp rejected the request ({response.status_code})",
    }


def list_whatsapp_numbers(api_token: str) -> dict:
    """The WhatsApp numbers on this WhatChimp account, so the owner picks one instead of typing an ID."""
    api_token = (api_token or "").strip()
    if not api_token:
        return {"success": False, "data": None, "error": "WhatChimp API key is missing"}

    result = _post("user/myInfo", {"apiToken": api_token})
    if not result["success"]:
        return result

    info = result["data"].get("message")
    bots = info.get("whatsapp_bots_details") if isinstance(info, dict) else None
    numbers = [
        {
            "phone_number_id": str(bot["phone_number_id"]),
            "display_phone_number": str(bot.get("display_phone_number") or ""),
            "business_name": str(bot.get("whatsapp_business_name") or ""),
        }
        for bot in bots or []
        if isinstance(bot, dict) and bot.get("phone_number_id")
    ]
    return {"success": True, "data": numbers, "error": None}


def _send(path: str, api_token: str, phone_number_id: str, to: str, fields: dict) -> dict:
    recipient = whatchimp_recipient(to)
    if not api_token or not phone_number_id or not recipient:
        return {"success": False, "data": None, "error": "WhatChimp API key, number or recipient is missing"}
    return _post(path, {"apiToken": api_token, "phone_number_id": str(phone_number_id),
                        "phone_number": recipient, **fields})


def send_whatchimp_text(api_token: str, phone_number_id: str, to: str, text: str) -> dict:
    return _send("whatsapp/send", api_token, phone_number_id, to, {"message": text or ""})


def send_whatchimp_file(api_token: str, phone_number_id: str, to: str, media_url: str, media_type: str,
                        caption: str = "") -> dict:
    fields = {"media_url": media_url or "", "media_type": media_type or "image"}
    if caption:
        fields["media_caption_text"] = caption
    return _send("whatsapp/send/file", api_token, phone_number_id, to, fields)


def send_whatchimp_buttons(api_token: str, phone_number_id: str, to: str, text: str, labels: list) -> dict:
    """Real tappable reply buttons; the customer's tap comes back as an ordinary message."""
    buttons = []
    for label in labels or []:
        title = str(label or "").strip()[:MAX_BUTTON_TITLE_LENGTH]
        if title:
            buttons.append({"id": f"btn_{len(buttons)}", "title": title})
        if len(buttons) == MAX_REPLY_BUTTONS:
            break
    return _send("whatsapp/send/interactive-buttons", api_token, phone_number_id, to,
                 {"message": text or "", "buttons": json.dumps(buttons)})
