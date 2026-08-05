"""Scrub raw secret values out of run output before it is persisted or streamed.

Belt-and-suspenders: secrets are only ever injected as env vars, but an agent
can still echo them (``env``, a misbehaving script, an error message that
dumps its environment), and that text flows straight into task_run_output and
the live Socket.IO stream. Replace any exact occurrence of a known secret
value with a masked placeholder before it leaves the orchestrator.
"""


def redact(text: str, secret_values: dict[str, str]) -> str:
    if not text or not secret_values:
        return text
    for name, value in secret_values.items():
        if value and value in text:
            text = text.replace(value, f"***{name}***")
    return text
