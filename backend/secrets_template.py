"""Resolve `{{secret.NAME}}` placeholders in task prompts, and mask resolved
secret values before they're persisted or streamed as run output.

Placeholders are expanded once, at execution time, against the encrypted
vault — never stored expanded. This keeps a task's prompt (and its edit
history) free of plaintext credentials while still letting the agent use
them.
"""

import re

from crypto import decrypt
from db import secrets as db_secrets

PLACEHOLDER_RE = re.compile(r"\{\{\s*secret\.([A-Za-z0-9_]+)\s*\}\}")

# Values shorter than this are never masked in output — redacting a 2-3
# character secret would blank out ordinary words throughout the run.
_MIN_MASK_LEN = 4


async def resolve_secrets(db, text: str) -> tuple[str, list[str], dict[str, str]]:
    """Expand every `{{secret.NAME}}` reference in `text`.

    Returns (resolved_text, missing_names, values_by_name). If any
    referenced secret doesn't exist, `text` is returned unresolved and
    `missing_names` lists what's absent — the caller should treat that as
    a fatal config error rather than send the raw placeholder to the model.
    """
    names = sorted(set(m.group(1).upper() for m in PLACEHOLDER_RE.finditer(text)))
    if not names:
        return text, [], {}

    missing: list[str] = []
    values: dict[str, str] = {}
    for name in names:
        row = await db_secrets.get_by_name(db, name)
        if not row:
            missing.append(name)
            continue
        values[name] = decrypt(row["value_encrypted"])

    if missing:
        return text, missing, values

    resolved = PLACEHOLDER_RE.sub(lambda m: values[m.group(1).upper()], text)
    return resolved, [], values


def redact_secret_values(content: str, values_by_name: dict[str, str]) -> str:
    """Mask any occurrence of a resolved secret's plaintext value.

    Defense in depth: even though the model only ever sees the real value
    (it needs it to be useful), an agent that echoes it back into its
    output shouldn't leave it sitting in run history or the live log
    stream.
    """
    if not values_by_name:
        return content
    for name, value in values_by_name.items():
        if len(value) >= _MIN_MASK_LEN and value in content:
            content = content.replace(value, f"***{name}***")
    return content
