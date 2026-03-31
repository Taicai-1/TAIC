"""Encryption helpers for sensitive data stored in DB (Slack tokens, etc.)

Uses Fernet symmetric encryption from the cryptography library.
Requires ENCRYPTION_KEY env var (base64-encoded 32-byte key).

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        if os.getenv("GOOGLE_CLOUD_PROJECT"):
            raise RuntimeError(
                "ENCRYPTION_KEY is required in production. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        logger.warning("ENCRYPTION_KEY not set - sensitive fields will be stored in plaintext (dev only)")
        return None
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:
        logger.error(f"Invalid ENCRYPTION_KEY: {e}")
        return None


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string. Returns prefixed ciphertext or plaintext if no key."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext
    encrypted = f.encrypt(plaintext.encode()).decode()
    return f"enc:{encrypted}"


def decrypt_value(stored: str) -> str:
    """Decrypt a stored value. Handles both encrypted (enc: prefix) and legacy plaintext."""
    if not stored:
        return stored
    if not stored.startswith("enc:"):
        return stored  # Legacy plaintext, return as-is
    f = _get_fernet()
    if f is None:
        logger.error("Cannot decrypt: ENCRYPTION_KEY not set")
        return None
    try:
        return f.decrypt(stored[4:].encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt value - invalid key or corrupted data")
        return None
