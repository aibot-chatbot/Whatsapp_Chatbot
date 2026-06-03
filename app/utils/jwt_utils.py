import os


def get_jwt_secret():
    secret = os.getenv("JWT_SECRET")
    if not secret or not secret.strip():
        raise RuntimeError("JWT_SECRET is not configured")
    return secret
