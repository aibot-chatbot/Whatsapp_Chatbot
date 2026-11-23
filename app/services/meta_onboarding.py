"""Meta Graph writes used only by an Embedded Signup completion."""

import secrets

import requests
from cryptography.fernet import InvalidToken

from app.utils.provider_secrets import provider_fernet
from app.utils.whatsapp_graph import graph_api_version


class RegistrationRateLimited(ValueError):
    pass


class PinEncryptionUnavailable(RuntimeError):
    pass


def registration_pin(previous_ciphertext):
    try:
        fernet = provider_fernet()
        if previous_ciphertext:
            return fernet.decrypt(previous_ciphertext.encode()).decode(), previous_ciphertext
        pin = f"{secrets.randbelow(1_000_000):06d}"
        encrypted = fernet.encrypt(pin.encode()).decode()
    except (KeyError, ValueError, InvalidToken):
        raise PinEncryptionUnavailable("Registration PIN encryption is unavailable.") from None
    return pin, encrypted


def _post(path, token, payload, failure):
    response = requests.post(
        f"https://graph.facebook.com/{graph_api_version()}/{path}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload, timeout=15,
    )
    try:
        result = response.json()
    except ValueError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    error = result.get("error")
    if isinstance(error, dict) and str(error.get("code")) == "133016":
        raise RegistrationRateLimited("Too many registration attempts. Try again in 72 hours.")
    if response.status_code != 200 or result.get("success") is not True or error:
        raise ValueError(failure)


def subscribe_waba(waba_id, token):
    _post(f"{waba_id}/subscribed_apps", token, {}, "Meta could not subscribe this WhatsApp Business Account.")


def register_number(phone_number_id, token, pin):
    _post(f"{phone_number_id}/register", token, {"messaging_product": "whatsapp", "pin": pin},
          "Meta could not register this phone number.")
