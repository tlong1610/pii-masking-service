"""Áp dụng MASK / PARTIAL / HMAC / REDACT / DROP / NULLIFY / KEEP lên giá trị; không bao giờ log giá trị PII thô."""

from __future__ import annotations

import logging
from typing import Any

from piimask.transform.hmac_hasher import hash_value

MASK_PLACEHOLDER = "***"

logger = logging.getLogger(__name__)


def partial_mask(value: Any) -> Any:
    """Partially mask value while preserving contextual shape (e.g. j***@example.com, 091***789)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return s
    if "@" in s:
        parts = s.split("@", 1)
        u = parts[0]
        domain = parts[1]
        if len(u) <= 1:
            u_masked = u + "***"
        else:
            u_masked = u[0] + "***" + (u[-1] if len(u) > 2 else "")
        return f"{u_masked}@{domain}"
    if s.isdigit():
        if len(s) >= 9:
            return f"{s[:3]}***{s[-3:]}"
        elif len(s) >= 4:
            return f"{s[:2]}***{s[-2:]}"
        return "***"
    if len(s) <= 4:
        return "***"
    return f"{s[:2]}***{s[-2:]}"


def redact_value(value: Any) -> Any:
    """Entity-level redaction (NER) for free text: keeps the sentence, replaces each PII entity by its tag.

    Non-text values carry no surrounding context worth keeping, so they are replaced whole.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return "[REDACTED]"
    from piimask.detection.ner_orchestrator import redact_free_text

    try:
        return redact_free_text(value)
    except Exception as exc:
        # Fail closed: a cell NER cannot process is withheld whole, never written raw, and one bad
        # cell does not abort the snapshot. Only the error type is logged, never the value.
        logger.warning("NER redaction failed (%s); cell replaced whole", type(exc).__name__)
        return "[REDACTED]"


def apply_action(
    value: Any,
    action: str,
    *,
    secret: str,
    key_version: str,
) -> tuple[bool, Any]:
    """Return (keep_column, new_value). DROP => keep_column False."""
    action_u = (action or "").upper()
    if action_u == "DROP":
        return False, None
    if action_u == "NULLIFY":
        return True, None
    if action_u == "REDACT":
        return True, redact_value(value)
    if action_u == "MASK":
        if value is None:
            return True, None
        return True, MASK_PLACEHOLDER
    if action_u == "PARTIAL":
        return True, partial_mask(value)
    if action_u == "HMAC":
        return True, hash_value(value, secret=secret, key_version=key_version)
    # KEEP and unknown treated as KEEP
    return True, value


def transform_row(
    row: dict[str, Any],
    column_actions: dict[str, str],
    *,
    secret: str,
    key_version: str,
) -> dict[str, Any]:
    """Transform one row. Columns not listed in column_actions are kept."""
    out: dict[str, Any] = {}
    for col, value in row.items():
        action = column_actions.get(col, "KEEP")
        keep, new_val = apply_action(value, action, secret=secret, key_version=key_version)
        if keep:
            out[col] = new_val
    return out


def transform_rows(
    rows: list[dict[str, Any]],
    column_actions: dict[str, str],
    *,
    secret: str,
    key_version: str,
) -> list[dict[str, Any]]:
    return [
        transform_row(r, column_actions, secret=secret, key_version=key_version) for r in rows
    ]


def filter_columns(columns: list[str], column_actions: dict[str, str]) -> list[str]:
    """Columns present after DROP."""
    return [c for c in columns if column_actions.get(c, "KEEP").upper() != "DROP"]

