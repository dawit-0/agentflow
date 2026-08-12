"""Encryption at rest for secret values stored in the `secrets` table.

AgentFlow is a local-first, single-user app with no auth layer, so there's
no KMS to lean on. The practical baseline is a symmetric key: an operator
can pin one via AGENTFLOW_SECRET_KEY (e.g. when the DB file is shared or
backed up somewhere), otherwise we generate one on first use and keep it
next to the DB, out of git.
"""

import os

from cryptography.fernet import Fernet

_KEY_ENV_VAR = "AGENTFLOW_SECRET_KEY"
_KEY_PATH = os.path.join(os.path.dirname(__file__), ".secret_key")

_fernet: Fernet | None = None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get(_KEY_ENV_VAR)
    if env_key:
        return env_key.encode()

    if os.path.exists(_KEY_PATH):
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
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
