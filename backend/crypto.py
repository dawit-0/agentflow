"""Symmetric encryption for secret values at rest.

The key is a local file generated on first use (never committed — see
.gitignore) so encrypted values in the SQLite database are useless without
the machine's key file, same threat model as Airflow's Fernet key.
"""

import os

from cryptography.fernet import Fernet

_KEY_PATH = os.path.join(os.path.dirname(__file__), ".secret_key")
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    if os.path.isfile(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    try:
        fd = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
        return key
    except FileExistsError:
        with open(_KEY_PATH, "rb") as f:
            return f.read().strip()


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
