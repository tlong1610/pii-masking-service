"""Unit tests for MASK / DROP / HMAC transform engine."""

import pytest

from piimask.transform.hmac_hasher import hash_value
from piimask.transform.mask_engine import MASK_PLACEHOLDER, apply_action

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


def test_keep_returns_value():
    assert apply_action("x", "KEEP", secret=SECRET, key_version=VERSION) == (True, "x")


@pytest.mark.parametrize("action", ["", "XOA", "NULLIFY", None])
def test_unknown_action_is_rejected_without_value_in_message(action):
    with pytest.raises(ValueError) as failure:
        apply_action("0912345678", action, secret=SECRET, key_version=VERSION)
    assert "0912345678" not in str(failure.value)
