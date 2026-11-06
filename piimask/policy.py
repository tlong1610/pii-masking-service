"""Chọn hành động che cho từng trường theo loại PII, bảng đề xuất ở mục 9 của Gate 0.

Không nhận giá trị, chỉ nhận kết quả phân loại. Mọi nhánh không chắc chắn đều dẫn tới che, không dẫn tới giữ nguyên.
"""

from dataclasses import asdict, dataclass

from piimask.detection.taxonomy import legal_group
from piimask.schemas import FieldScanResult, PolicyAction

# Loại không có ở đây dùng MASK. Bộ phát hiện đang gộp số thẻ và số tài khoản vào CREDIT_CARD nên loại đó cũng MASK,
# hành động chặt hơn của hai loại.
_ACTIONS = {
    "EMAIL": PolicyAction.HMAC,
    "IP_ADDRESS": PolicyAction.HMAC,
    "PHONE": PolicyAction.PARTIAL,
    "FREE_TEXT_PII": PolicyAction.REDACT,
}
_NOT_PERSONAL = frozenset({"TRACKING_CODE", "MONEY_ALONE", "NOT_PERSONAL_DATA", "TAX_CODE_ORG", "CITY"})

# Tầng quy tắc kết luận cột rỗng chỉ từ vài mẫu đầu, nên cột đó vẫn được che nếu về sau có giá trị.
_NO_PII_TYPE = frozenset({"EMPTY_COLUMN"})


@dataclass(frozen=True)
class FieldDecision:
    path: str
    pii_type: str | None
    group: str | None
    action: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def undecided(path: str, reason: str = "chua_ket_luan") -> FieldDecision:
    """Trường chưa có kết luận bị che toàn bộ cho tới khi người duyệt quyết định."""
    return FieldDecision(path, None, None, PolicyAction.MASK.value, reason)


def decide(path: str, result: FieldScanResult | None, join_keys: frozenset[str] = frozenset()) -> FieldDecision:
    """join_keys là tên trường viết thường dùng để nối bảng: CCCD ở đó dùng HMAC thay vì MASK."""
    if result is None or result.inferred_pii_type in _NO_PII_TYPE:
        return undecided(path)

    pii_type = result.inferred_pii_type
    if pii_type in _NOT_PERSONAL:
        return FieldDecision(path, None, None, PolicyAction.KEEP.value, "khong_phai_du_lieu_ca_nhan")

    action = _ACTIONS.get(pii_type, PolicyAction.MASK)
    if path.lower() in join_keys:
        action = PolicyAction.HMAC
    return FieldDecision(path, pii_type, legal_group(pii_type), action.value, "phat_hien")
