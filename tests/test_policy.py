import pytest

from piimask.policy import decide, undecided
from piimask.schemas import FieldScanResult


def _result(pii_type):
    return FieldScanResult(
        field_name="x",
        inferred_pii_type=pii_type,
        confidence=1.0,
        recommended_action="KEEP",
        reasoning="",
    )


@pytest.mark.parametrize(
    ("pii_type", "action"),
    [
        ("FULL_NAME", "MASK"),
        ("CCCD", "MASK"),
        ("DOB", "MASK"),
        ("ADDRESS", "MASK"),
        ("TAX_CODE", "MASK"),
        ("CREDIT_CARD", "MASK"),
        ("PHONE", "PARTIAL"),
        ("EMAIL", "HMAC"),
        ("IP_ADDRESS", "HMAC"),
        ("FREE_TEXT_PII", "REDACT"),
        ("BIOMETRIC_FILE", "MASK"),
    ],
)
def test_action_follows_pii_type(pii_type, action):
    assert decide("f", _result(pii_type)).action == action


@pytest.mark.parametrize("pii_type", ["TRACKING_CODE", "MONEY_ALONE", "NOT_PERSONAL_DATA", "TAX_CODE_ORG", "CITY"])
def test_not_personal_data_is_kept(pii_type):
    decision = decide("f", _result(pii_type))
    assert decision.action == "KEEP" and decision.pii_type is None


def test_recommended_action_of_scanner_does_not_override_policy():
    # Bộ quét đề xuất KEEP ở _result nhưng loại PII vẫn quyết định hành động.
    assert decide("f", _result("EMAIL")).action == "HMAC"


def test_cccd_on_join_key_uses_hmac():
    assert decide("IdNumber", _result("CCCD"), frozenset({"idnumber"})).action == "HMAC"
    assert decide("c1", _result("CCCD"), frozenset({"idnumber"})).action == "MASK"


def test_unknown_type_is_masked():
    assert decide("f", _result("LOAI_MOI")).action == "MASK"


def test_undecided_and_empty_columns_are_masked():
    assert decide("f", None).action == "MASK"
    assert decide("f", None).reason == "chua_ket_luan"
    assert decide("f", _result("EMPTY_COLUMN")).action == "MASK"
    assert undecided("f", "ngoai_pham_vi_quet").action == "MASK"


def test_group_comes_from_legal_group():
    assert decide("f", _result("CREDIT_CARD")).group == "nhay_cam"
    assert decide("f", _result("CCCD")).group == "co_ban"
