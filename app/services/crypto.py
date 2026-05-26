import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import get_settings

settings = get_settings()


def _key() -> bytes:
    return bytes.fromhex(settings.plugin_api_key_secret)


def encrypt_api_key(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_api_key(ciphertext: str) -> str:
    raw = base64.b64decode(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(_key()).decrypt(nonce, ct, None).decode()
