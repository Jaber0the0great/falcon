import os
from cryptography.fernet import Fernet, MultiFernet

_CIPHER = None

def _get_cipher():
    global _CIPHER
    if _CIPHER is not None:
        return _CIPHER
    key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY environment variable is not set. "
            "The application cannot start without an encryption key."
        )
    if isinstance(key, str):
        key = key.encode()

    # Collect previous keys for rotation support.
    # Decryption tries all keys; encryption always uses the current (first) key.
    old_keys_str = os.environ.get('ENCRYPTION_KEY_OLD_KEYS', '')
    old_keys = [k.strip().encode() if isinstance(k, str) else k
                for k in old_keys_str.split(',') if k.strip()]

    all_key_bytes = [key] + old_keys
    ferns = [Fernet(k) for k in all_key_bytes]
    _CIPHER = ferns[0] if len(ferns) == 1 else MultiFernet(ferns)
    return _CIPHER

def encrypt_text(text):
    if not text:
        return text
    try:
        return _get_cipher().encrypt(text.encode()).decode()
    except Exception:
        return text

def decrypt_text(encrypted_text):
    if not encrypted_text:
        return encrypted_text
    try:
        return _get_cipher().decrypt(encrypted_text.encode()).decode()
    except Exception:
        return encrypted_text

def is_encrypted(text):
    """Return True if *text* is a valid Fernet token decryptable with any known key."""
    if not text:
        return False
    try:
        _get_cipher().decrypt(text.encode())
        return True
    except Exception:
        return False
