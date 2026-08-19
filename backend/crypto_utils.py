"""Symmetric encryption for secret values at rest.

The key is a Fernet key, read from the ``AGENTFLOW_SECRET_KEY`` env var if
set (useful for containerized/production deployments), otherwise generated
once and persisted to a local, gitignored file next to the database so it
survives restarts. Losing this file makes existing encrypted secrets
unrecoverable — same trade-off as Airflow's ``fernet_key``.
"""

import os

from cryptography.fernet import Fernet

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


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
