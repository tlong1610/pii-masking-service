from enum import StrEnum


class LegalGroup(StrEnum):
    """Nhóm theo pháp luật: cơ bản (Điều 3) và nhạy cảm (Điều 4) của Nghị định 356/2025/NĐ-CP."""

    CO_BAN = "co_ban"
    NHAY_CAM = "nhay_cam"


class PIIType(StrEnum):
    CCCD = "CCCD"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    ADDRESS = "ADDRESS"
    DOB = "DOB"
    TAX_CODE = "TAX_CODE"
    TRACKING_CODE = "TRACKING_CODE"
    MONEY_ALONE = "MONEY_ALONE"


# CCCD là cơ bản, chỉ ảnh thẻ căn cước mới là nhạy cảm. Loại không có ở đây được coi là cơ bản (Điều 3 k11).
_NHAY_CAM_TYPES = frozenset({"BANK_ACCOUNT", "CREDIT_CARD", "PASSWORD", "TOKEN", "GPS"})


def legal_group(pii_type: str | None) -> str | None:
    """Nhóm pháp lý của một loại PII; None nếu không phải dữ liệu cá nhân."""
    if pii_type is None:
        return None
    return (LegalGroup.NHAY_CAM if pii_type in _NHAY_CAM_TYPES else LegalGroup.CO_BAN).value
