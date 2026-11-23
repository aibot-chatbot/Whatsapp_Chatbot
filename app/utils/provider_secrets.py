import os

from cryptography.fernet import Fernet, MultiFernet


def provider_fernet():
    # Newest key first so existing ciphertext remains readable during rotation.
    return MultiFernet([Fernet(key.strip().encode()) for key in os.environ["AI_KEY_ENCRYPTION_KEY"].split(",")])
