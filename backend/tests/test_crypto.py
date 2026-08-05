"""Unit tests for secret encryption and output redaction (sync, no DB)."""

import crypto
from secret_redact import redact


def test_crypto_round_trip():
    token = crypto.encrypt("super-secret-value")
    assert token != "super-secret-value"
    assert crypto.decrypt(token) == "super-secret-value"


def test_redact_masks_known_values():
    out = redact("token is sk-abc123 in the log", {"MY_TOKEN": "sk-abc123"})
    assert "sk-abc123" not in out
    assert "***MY_TOKEN***" in out


def test_redact_noop_without_secrets():
    assert redact("hello world", {}) == "hello world"


def test_redact_handles_empty_text():
    assert redact("", {"X": "y"}) == ""


def test_redact_masks_multiple_secrets_independently():
    out = redact("a=1 b=2", {"A": "1", "B": "2"})
    assert out == "a=***A*** b=***B***"
