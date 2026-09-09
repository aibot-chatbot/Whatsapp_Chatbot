import datetime
import hmac
from hashlib import sha256

import jwt

from app.utils.jwt_utils import get_jwt_secret


PASSWORD_FINGERPRINT_CLAIM = "pwdv"
PASSWORD_FINGERPRINT_PREFIX = "v1:"


class AuthTokenValidationError(ValueError):
    """Raised when a token no longer matches the current account credentials."""


def _password_hash_from_user(user):
    if not isinstance(user, dict) or "password_hash" not in user:
        raise AuthTokenValidationError("password_hash_not_loaded")
    password_hash = user.get("password_hash")
    if password_hash is None:
        return ""
    if not isinstance(password_hash, str):
        raise AuthTokenValidationError("password_hash_invalid")
    return password_hash


def build_password_fingerprint(user):
    password_hash = _password_hash_from_user(user)
    secret = get_jwt_secret()
    digest = hmac.new(
        secret.encode("utf-8"),
        ("pwdv:" + password_hash).encode("utf-8"),
        sha256,
    ).hexdigest()
    return PASSWORD_FINGERPRINT_PREFIX + digest


def create_auth_token(user):
    now = datetime.datetime.now(datetime.timezone.utc)
    token_payload = {
        "user_id": user["id"],
        "company_id": user.get("company_id"),
        "email": user["email"],
        "role": user["role"],
        "iat": now,
        "exp": now + datetime.timedelta(hours=24),
        PASSWORD_FINGERPRINT_CLAIM: build_password_fingerprint(user),
    }
    return jwt.encode(token_payload, get_jwt_secret(), algorithm="HS256")


def validate_password_fingerprint(claims, current_user):
    claim = claims.get(PASSWORD_FINGERPRINT_CLAIM) if isinstance(claims, dict) else None
    if (
        not isinstance(claim, str)
        or not claim.startswith(PASSWORD_FINGERPRINT_PREFIX)
        or len(claim) != len(PASSWORD_FINGERPRINT_PREFIX) + 64
    ):
        raise AuthTokenValidationError("password_fingerprint_missing")
    expected = build_password_fingerprint(current_user)
    if not hmac.compare_digest(claim, expected):
        raise AuthTokenValidationError("password_fingerprint_mismatch")
