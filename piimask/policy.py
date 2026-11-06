"""Chọn hành động che cho từng trường theo loại PII, bảng đề xuất ở mục 9 của Gate 0.

Mọi nhánh không chắc chắn đều dẫn tới che, không dẫn tới giữ nguyên. Mẫu chỉ dùng trong bộ nhớ, quyết định không chứa
giá trị.
"""

from collections import Counter
from dataclasses import asdict, dataclass

from piimask.detection.regex_ner import RegexNERScanner
from piimask.detection.taxonomy import legal_group
from piimask.schemas import FieldScanResult, PolicyAction

# Loại không có ở đây dùng MASK. Bộ phát hiện đang gộp số thẻ và số tài khoản vào CREDIT_CARD nên loại đó cũng MASK,
# hành động chặt hơn của hai loại.
_ACTIONS = {
    "EMAIL": PolicyAction.HMAC,
    "IP_ADDRESS": PolicyAction.HMAC,
    "SESSION_ID": PolicyAction.HMAC,
    "PHONE": PolicyAction.PARTIAL,
    "FREE_TEXT_PII": PolicyAction.REDACT,
}
_NOT_PERSONAL = frozenset({"TRACKING_CODE", "MONEY_ALONE", "NOT_PERSONAL_DATA", "TAX_CODE_ORG", "CITY"})

# Tầng quy tắc kết luận cột rỗng chỉ từ vài mẫu đầu, nên cột đó vẫn được che nếu về sau có giá trị.
_NO_PII_TYPE = frozenset({"EMPTY_COLUMN"})


# Phần lớn mẫu của trường KEEP khớp trọn một định dạng PII: đó là định dạng bình thường của trường, ví dụ mã vận đơn 12 số.
_ROUTINE_SHARE = 0.5
_format_scanner = RegexNERScanner()


@dataclass(frozen=True)
class FieldDecision:
    """guard_exempt là các loại mà lớp chặn cuối bỏ qua ở trường KEEP này."""

    path: str
    pii_type: str | None
    group: str | None
    action: str
    reason: str
    guard_exempt: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def routine_formats(samples: list[str]) -> tuple[str, ...]:
    """Loại PII trùng định dạng bình thường của trường. Giá trị hiếm khác định dạng đó vẫn bị lớp chặn cuối bắt."""
    counts: Counter = Counter()
    for sample in samples:
        for match in _format_scanner.scan_text(sample):
            if match.start == 0 and match.end == len(sample):
                counts[match.pii_type] += 1
    return tuple(sorted(name for name, count in counts.items() if count >= len(samples) * _ROUTINE_SHARE))


def undecided(path: str, reason: str = "chua_ket_luan") -> FieldDecision:
    """Trường chưa có kết luận bị che toàn bộ cho tới khi người duyệt quyết định."""
    return FieldDecision(path, None, None, PolicyAction.MASK.value, reason)


def decide(
    path: str,
    result: FieldScanResult | None,
    join_keys: frozenset[str] = frozenset(),
    samples: list[str] | None = None,
) -> FieldDecision:
    """join_keys là tên trường viết thường dùng để nối bảng: CCCD ở đó dùng HMAC thay vì MASK."""
    if result is None or result.inferred_pii_type in _NO_PII_TYPE:
        return undecided(path)

    pii_type = result.inferred_pii_type
    if pii_type in _NOT_PERSONAL:
        exempt = routine_formats(samples or [])
        return FieldDecision(path, None, None, PolicyAction.KEEP.value, "khong_phai_du_lieu_ca_nhan", exempt)

    action = _ACTIONS.get(pii_type, PolicyAction.MASK)
    if path.lower() in join_keys:
        action = PolicyAction.HMAC
    return FieldDecision(path, pii_type, legal_group(pii_type), action.value, "phat_hien")
