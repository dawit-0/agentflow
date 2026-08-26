"""Symmetric encryption for secret values at rest.

The key is generated once and stored outside the SQLite database (and
outside git) so a leaked ``agentflow.db`` file alone can't be decrypted.
Override the key path or supply the key directly via ``AGENTFLOW_SECRET_KEY``
for containerized / multi-instance deployments.
"""

import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_PATH = os.path.join(os.path.dirname(__file__), ".secret_key")
_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("AGENTFLOW_SECRET_KEY")
    if env_key:
        return env_key.encode("utf-8")

    if os.path.isfile(_KEY_PATH):
        with open(_KEY_PATH, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    fd = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError("secret value could not be decrypted — encryption key changed?")
