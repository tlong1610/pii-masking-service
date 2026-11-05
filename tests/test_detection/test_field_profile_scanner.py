import pytest

from piimask.detection.field_profile_scanner import FieldProfileScanner
from piimask.schemas import FieldProfile, PolicyAction


@pytest.fixture
def scanner():
    return FieldProfileScanner()


def test_tracking_code_not_cccd(scanner):
    """
    Test edge case: Mã vận đơn dài 12 ký tự giống hệt CCCD.
    Kỳ vọng: Scanner nhận diện qua tên 'tracking_code' và bỏ qua (KEEP).
    """
    profile = FieldProfile(
        engine="postgresql",
        table_or_collection="orders",
        path="tracking_code",
        data_type="string",
        statistics={"max_len": 12, "min_len": 12}
    )
    result = scanner.scan(profile)
    assert result is not None
    assert result.action == PolicyAction.KEEP
    assert result.classification == "NON_PERSONAL"
    assert "tracking_code" in result.reason.lower()


def test_order_id_not_pii(scanner):
    """
    Test edge case: Mã đơn hàng (order_id)
    Kỳ vọng: Scanner nhận diện đây không phải dữ liệu cá nhân (KEEP).
    """
    profile = FieldProfile(
        engine="postgresql",
        table_or_collection="orders",
        path="order_id",
        data_type="integer"
    )
    result = scanner.scan(profile)
    assert result is not None
    assert result.action == PolicyAction.KEEP
    assert result.classification == "NON_PERSONAL"


def test_amount_standalone(scanner):
    """
    Test edge case: Cước phí/Số tiền (shipping_fee)
    Kỳ vọng: Scanner đưa vào dạng KEEP (Tiền đứng riêng không phải PII).
    """
    profile = FieldProfile(
        engine="postgresql",
        table_or_collection="orders",
        path="shipping_fee",
        data_type="float"
    )
    result = scanner.scan(profile)
    assert result is not None
    assert result.action == PolicyAction.KEEP
    assert result.classification == "NON_PERSONAL"


def test_mongo_nested_cccd(scanner):
    """
    Test logic: Flatten Mongo path ('identity.cccd') và nhận diện chuẩn xác.
    Kỳ vọng: action = HMAC (do là CCCD).
    """
    profile = FieldProfile(
        engine="mongodb",
        table_or_collection="customers",
        path="identity.cccd",
        data_type="string",
        statistics={"max_len": 12, "min_len": 12}
    )
    result = scanner.scan(profile)
    assert result is not None
    assert result.action == PolicyAction.HMAC
    assert "BASIC" in result.classification # Dựa vào taxonomy


def test_ambiguous_unknown_no_keyword(scanner):
    """
    Test trường hợp mập mờ (Ambiguous): Cột 'notes' kiểu string.
    Kỳ vọng: Rules không dám quyết, trả về None để đẩy qua nhánh LLM.
    """
    profile = FieldProfile(
        engine="postgresql",
        table_or_collection="customers",
        path="notes",
        data_type="string",
        statistics={"max_len": 255}
    )
    result = scanner.scan(profile)
    assert result is None


def test_national_id_is_never_non_personal(scanner):
    """Regression: the '_id' negative keyword used to win over the CCCD name rule."""
    profile = FieldProfile(
        engine="postgresql",
        table_or_collection="customers",
        path="national_id",
        data_type="string",
        statistics={"max_len": 9, "min_len": 9},
    )
    result = scanner.scan(profile)
    assert result is None or result.classification != "NON_PERSONAL"
