import os
from cryptography.fernet import Fernet

_key = None
_fernet = None


def setup(key_file):
    """Initialize encryption with a key file. Creates key if it doesn't exist."""
    global _key, _fernet
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    if os.path.exists(key_file):
        with open(key_file, "rb") as f:
            _key = f.read()
    else:
        _key = Fernet.generate_key()
        with open(key_file, "wb") as f:
            f.write(_key)
    _fernet = Fernet(_key)


def encrypt(text: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext."""
    if _fernet is None:
        raise RuntimeError("Encryption not initialized. Call setup() first.")
    return _fernet.encrypt(text.encode()).decode()


def decrypt(cipher: str) -> str:
    """Decrypt a base64-encoded ciphertext back to string."""
    if _fernet is None:
        raise RuntimeError("Encryption not initialized. Call setup() first.")
    return _fernet.decrypt(cipher.encode()).decode()
