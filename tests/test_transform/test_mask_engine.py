"""Unit tests for MASK / DROP / HMAC transform engine."""

from piimask.transform.hmac_hasher import hash_value
from piimask.transform.mask_engine import (
    MASK_PLACEHOLDER,
    apply_action,
    filter_columns,
    transform_row,
)

SECRET = "test-secret"
VERSION = "v1"


def test_mask_and_drop_and_hmac():
    keep, masked = apply_action("secret", "MASK", secret=SECRET, key_version=VERSION)
    assert keep and masked == MASK_PLACEHOLDER

    keep, _ = apply_action("x", "DROP", secret=SECRET, key_version=VERSION)
    assert keep is False

    keep, digest = apply_action("CCCD1", "HMAC", secret=SECRET, key_version=VERSION)
    assert keep and digest == hash_value("CCCD1", secret=SECRET, key_version=VERSION)

    keep, null_digest = apply_action(None, "HMAC", secret=SECRET, key_version=VERSION)
    assert keep and null_digest is None


def test_transform_row_drops_column():
    row = {"cccd": "001", "phone": "090", "note": "hi"}
    actions = {"cccd": "HMAC", "phone": "MASK", "note": "DROP"}
    out = transform_row(row, actions, secret=SECRET, key_version=VERSION)
    assert "note" not in out
    assert out["phone"] == MASK_PLACEHOLDER
    assert out["cccd"] == hash_value("001", secret=SECRET, key_version=VERSION)
    assert filter_columns(["cccd", "phone", "note"], actions) == ["cccd", "phone"]
