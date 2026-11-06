"""Chọn hành động che cho từng trường theo loại PII, bảng đề xuất ở mục 9 của Gate 0.

Mọi nhánh không chắc chắn đều dẫn tới che, không dẫn tới giữ nguyên. Mẫu chỉ dùng trong bộ nhớ, quyết định không chứa
giá trị.
"""

from collections import Counter
from dataclasses import asdict, dataclass, replace

from piimask.detection.regex_ner import RegexNERScanner
from piimask.detection.taxonomy import legal_group
from piimask.schemas import FieldScanResult, PolicyAction

# Loại không có ở đây dùng MASK. Bộ phát hiện đang gộp số thẻ và số tài khoản vào CREDIT_CARD nên loại đó cũng MASK,
# hành động chặt hơn của hai loại.
_ACTIONS = {
    "EMAIL": PolicyAction.HMAC,
    "IP_ADDRESS": PolicyAction.HMAC,
    "SESSION_ID": PolicyAction.HMAC,
    "CUSTOMER_ID": PolicyAction.HMAC,
    "VIN": PolicyAction.HMAC,
    "DEVICE_SERIAL": PolicyAction.HMAC,
    "PHONE": PolicyAction.PARTIAL,
    "FREE_TEXT_PII": PolicyAction.REDACT,
}
_NOT_PERSONAL = frozenset({"TRACKING_CODE", "MONEY_ALONE", "NOT_PERSONAL_DATA", "TAX_CODE_ORG", "CITY"})

# Tầng quy tắc kết luận cột rỗng chỉ từ vài mẫu đầu, nên cột đó vẫn được che nếu về sau có giá trị.
_NO_PII_TYPE = frozenset({"EMPTY_COLUMN"})


# Dữ liệu định danh con người: collection có một trong các loại này thì số khung, serial trong đó gắn với người.
_PERSON_TYPES = frozenset({"FULL_NAME", "PHONE", "EMAIL", "CCCD", "CUSTOMER_ID"})
_ASSET_TYPES = frozenset({"VIN", "DEVICE_SERIAL"})
# Của khách doanh nghiệp thì không phải dữ liệu cá nhân. Suy luận theo ngữ cảnh, mentor có thể quyết khác.
_ENTERPRISE_EXEMPT_TYPES = frozenset({"CUSTOMER_ID", "TAX_CODE"}) | _ASSET_TYPES

# Phần lớn mẫu của trường KEEP khớp trọn một định dạng PII: đó là định dạng bình thường của trường, ví dụ mã vận đơn 12 số.
_ROUTINE_SHARE = 0.5
_format_scanner = RegexNERScanner()


@dataclass(frozen=True)
class FieldDecision:
    """guard_exempt là các loại mà lớp chặn cuối bỏ qua khi giữ nguyên ô của trường này.

    enterprise_flag khác rỗng nghĩa là dòng có cờ đó bằng True thì giữ nguyên, dòng còn lại áp action.
    """

    path: str
    pii_type: str | None
    group: str | None
    action: str
    reason: str
    guard_exempt: tuple[str, ...] = ()
    enterprise_flag: str | None = None
    confidence: float | None = None

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


def _is_enterprise_exempt(path: str, pii_type: str | None) -> bool:
    # Tên đăng ký thuế của khách doanh nghiệp là tên công ty.
    return pii_type in _ENTERPRISE_EXEMPT_TYPES or (pii_type == "FULL_NAME" and "tax" in path.lower())


def apply_context(plan: dict[str, FieldDecision], enterprise_flag: str | None = None) -> dict[str, FieldDecision]:
    """Áp ngữ cảnh của cả collection lên quyết định từng trường.

    Không có dữ liệu định danh người thì số khung, serial không phải dữ liệu cá nhân. Có trường cờ doanh nghiệp thì
    các loại có điều kiện chỉ che ở dòng khách cá nhân. Không có cờ thì luôn che.
    """
    person_linked = any(decision.pii_type in _PERSON_TYPES for decision in plan.values())
    has_flag = enterprise_flag is not None and enterprise_flag in plan
    result = {}
    for path, decision in plan.items():
        if decision.pii_type in _ASSET_TYPES and not person_linked:
            decision = FieldDecision(path, None, None, PolicyAction.KEEP.value, "khong_gan_voi_nguoi")
        elif has_flag and _is_enterprise_exempt(path, decision.pii_type):
            decision = replace(decision, enterprise_flag=enterprise_flag)
        result[path] = decision
    return result


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
        return FieldDecision(
            path,
            None,
            None,
            PolicyAction.KEEP.value,
            "khong_phai_du_lieu_ca_nhan",
            exempt,
            confidence=result.confidence,
        )

    action = _ACTIONS.get(pii_type, PolicyAction.MASK)
    if path.lower() in join_keys:
        action = PolicyAction.HMAC
    exempt = routine_formats(samples or []) if _is_enterprise_exempt(path, pii_type) else ()
    return FieldDecision(
        path, pii_type, legal_group(pii_type), action.value, "phat_hien", exempt, confidence=result.confidence
    )
