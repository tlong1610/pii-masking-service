"""HMAC-SHA-256 hasher for join keys — keyed digest, not encryption."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any


def normalize_for_hmac(value: Any) -> str | None:
    """Normalize a value before hashing. Null/missing stay null (no shared digest)."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value).strip()
    return text if text else None


def hash_value(
    value: Any,
    *,
    secret: str,
    key_version: str,
) -> str | None:
    """Return hex HMAC-SHA-256 digest, or None when value is null/missing.

    Same input + same secret/key_version → same digest.
    Different secret or key_version → different digest.
    Never uses raw (unkeyed) SHA; this is a one-way keyed hash, not encryption.
    """
    normalized = normalize_for_hmac(value)
    if normalized is None:
        return None
    if not secret:
        raise ValueError("HMAC secret must not be empty")
    if not key_version:
        raise ValueError("HMAC key_version must not be empty")

    # Bind key_version into the HMAC key material so rotating version changes digests.
    key_material = f"{secret}:{key_version}".encode()
    message = normalized.encode("utf-8")
    return hmac.new(key_material, message, hashlib.sha256).hexdigest()
