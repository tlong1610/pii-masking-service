import pytest

from piimask.policy import apply_context, decide, undecided
from piimask.schemas import FieldScanResult


def _result(pii_type):
    return FieldScanResult(
        field_name="x",
        inferred_pii_type=pii_type,
        confidence=1.0,
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


@pytest.mark.parametrize(
    ("pii_type", "action", "group"),
    [
        ("PASSWORD", "MASK", "nhay_cam"),
        ("TOKEN", "MASK", "nhay_cam"),
        ("GPS", "MASK", "nhay_cam"),
        ("SESSION_ID", "HMAC", "co_ban"),
    ],
)
def test_secret_types(pii_type, action, group):
    decision = decide("f", _result(pii_type))
    assert (decision.action, decision.group) == (action, group)


def _plan(**types):
    return {path: decide(path, _result(pii_type)) for path, pii_type in types.items()}


def test_serial_in_collection_without_people_is_kept():
    plan = apply_context(_plan(Serial="DEVICE_SERIAL", Vin="VIN", Status="NOT_PERSONAL_DATA"))
    assert plan["Serial"].action == "KEEP" and plan["Serial"].reason == "khong_gan_voi_nguoi"
    assert plan["Vin"].action == "KEEP"


def test_serial_linked_to_a_person_is_hashed():
    plan = apply_context(_plan(Serial="DEVICE_SERIAL", Name="FULL_NAME"))
    assert plan["Serial"].action == "HMAC" and plan["Serial"].pii_type == "DEVICE_SERIAL"


def test_enterprise_condition_applies_only_when_flag_field_exists():
    types = {"CustomerId": "CUSTOMER_ID", "Tax": "TAX_CODE", "Phone": "PHONE", "TaxRegistrationName": "FULL_NAME"}
    plan = apply_context({**_plan(**types), "Flag": decide("Flag", _result("NOT_PERSONAL_DATA"))}, "Flag")
    assert plan["CustomerId"].enterprise_flag == "Flag"
    assert plan["Tax"].enterprise_flag == "Flag"
    assert plan["TaxRegistrationName"].enterprise_flag == "Flag"
    assert plan["Phone"].enterprise_flag is None

    without_flag = apply_context(_plan(**types), "Flag")
    assert without_flag["CustomerId"].enterprise_flag is None
    assert without_flag["CustomerId"].action == "HMAC"


def test_customer_id_is_not_personal_only_through_the_flag():
    assert decide("CustomerId", _result("CUSTOMER_ID")).action == "HMAC"
