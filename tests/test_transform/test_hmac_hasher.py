"""Unit tests for HMAC-SHA-256 join-key hasher."""

import hashlib
import hmac

import pytest

from piimask.transform.hmac_hasher import hash_value, normalize_for_hmac

SECRET_V1 = "test-secret-do-not-use-in-prod"
VERSION_A = "v1"
VERSION_B = "v2"


class TestNormalizeForHmac:
    def test_none_stays_none(self):
        assert normalize_for_hmac(None) is None

    def test_empty_and_whitespace_are_missing(self):
        assert normalize_for_hmac("") is None
        assert normalize_for_hmac("   ") is None

    def test_strips_string(self):
        assert normalize_for_hmac("  cust-1  ") == "cust-1"

    def test_int_and_float(self):
        assert normalize_for_hmac(42) == "42"
        assert normalize_for_hmac(3.14) == "3.14"


class TestHashValue:
    def test_null_and_missing_do_not_share_a_digest(self):
        assert hash_value(None, secret=SECRET_V1, key_version=VERSION_A) is None
        assert hash_value("", secret=SECRET_V1, key_version=VERSION_A) is None
        assert hash_value("  ", secret=SECRET_V1, key_version=VERSION_A) is None

    def test_same_input_same_key_version_same_digest(self):
        a = hash_value("CUST-001", secret=SECRET_V1, key_version=VERSION_A)
        b = hash_value("CUST-001", secret=SECRET_V1, key_version=VERSION_A)
        assert a is not None
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_different_key_version_different_digest(self):
        a = hash_value("CUST-001", secret=SECRET_V1, key_version=VERSION_A)
        b = hash_value("CUST-001", secret=SECRET_V1, key_version=VERSION_B)
        assert a != b

    def test_different_secret_different_digest(self):
        a = hash_value("CUST-001", secret=SECRET_V1, key_version=VERSION_A)
        b = hash_value("CUST-001", secret="other-secret", key_version=VERSION_A)
        assert a != b

    def test_different_input_different_digest(self):
        a = hash_value("CUST-001", secret=SECRET_V1, key_version=VERSION_A)
        b = hash_value("CUST-002", secret=SECRET_V1, key_version=VERSION_A)
        assert a != b

    def test_uses_hmac_not_raw_sha(self):
        value = "CUST-001"
        digest = hash_value(value, secret=SECRET_V1, key_version=VERSION_A)
        raw_sha = hashlib.sha256(value.encode("utf-8")).hexdigest()
        assert digest != raw_sha

        expected = hmac.new(
            f"{SECRET_V1}:{VERSION_A}".encode(),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert digest == expected

    def test_rejects_empty_secret_or_version(self):
        with pytest.raises(ValueError, match="secret"):
            hash_value("x", secret="", key_version=VERSION_A)
        with pytest.raises(ValueError, match="key_version"):
            hash_value("x", secret=SECRET_V1, key_version="")
