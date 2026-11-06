import re

from piimask.detection.regex_patterns import (
    HIGH_CONFIDENCE_COLUMNS,
    NEGATIVE_COLUMNS,
    REGEX_PATTERNS,
    classify_name_column,
    is_generic_id_column,
    match_column_keyword,
    name_tokens,
)
from piimask.schemas import ColumnProfile, FieldScanResult

_DATETIME_TYPE_PREFIXES = ("date", "timestamp", "time")
_DATETIME_NAME_SUFFIXES = frozenset({"date", "at", "time", "timestamp", "datetime", "ngay"})
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?.*)?$")


def _is_event_datetime(col_profile: ColumnProfile) -> bool:
    """A date/time column (by SQL type, or *_date/*_at name with ISO samples) that is not a birth date."""
    data_type = (col_profile.data_type or "").lower()
    if data_type.startswith(_DATETIME_TYPE_PREFIXES):
        return True
    tokens = name_tokens(col_profile.column_name)
    samples = [str(sample).strip() for sample in col_profile.samples if str(sample).strip()]
    return bool(tokens) and tokens[-1] in _DATETIME_NAME_SUFFIXES and bool(samples) and all(
        _ISO_DATE.match(sample) for sample in samples
    )


class RuleBasedScanner:
    """
    Phân loại trường bằng quy tắc và regex.
    Nhiệm vụ: Chặn ngay lập tức các PII rõ ràng (như CCCD, Email, Phone)
    hoặc bỏ qua các loại chắc chắn không phải PII (Mã vận đơn, số tiền).
    Không chắc chắn thì trả None: chính sách che toàn bộ trường đó cho tới khi người duyệt quyết định.
    """

    def __init__(self, match_threshold: float = 0.5):
        # Tỷ lệ % số samples tối thiểu phải khớp Regex để kết luận là PII
        # Mặc định: 50% (VD: 3/5 mẫu là số điện thoại thì cột đó chứa SĐT)
        self.match_threshold = match_threshold

    def _check_column_name(self, column_name: str, keyword_dict: dict) -> str | None:
        """
        Kiểm tra tên cột có chứa từ khóa (theo NGUYÊN TỪ, không phải chuỗi con).
        Returns: PII Type hoặc None.
        """
        return match_column_keyword(column_name, keyword_dict)

    def _check_samples_regex(self, pii_type: str, samples: list[str]) -> float:
        """
        Chạy Regex tương ứng của loại PII lên danh sách samples.
        Returns: Tỷ lệ khớp (0.0 đến 1.0)
        """
        if not samples:
            return 0.0

        pattern = REGEX_PATTERNS.get(pii_type)
        if not pattern:
            return 0.0

        match_count = sum(1 for sample in samples if pattern.match(str(sample).strip()))
        return match_count / len(samples)

    def _negative_result(self, col_profile: ColumnProfile, negative_type: str) -> FieldScanResult:
        return FieldScanResult(
            field_name=col_profile.column_name,
            inferred_pii_type=negative_type,
            confidence=1.0,
            reasoning=f"Matched negative keyword for {negative_type}; no PII pattern in name or samples.",
        )

    def classify(self, col_profile: ColumnProfile) -> FieldScanResult | None:
        """Chỉ trả về kết quả nếu khớp 100% (chắc chắn PII hoặc chắc chắn KHÔNG phải); mập mờ thì trả None."""
        tbl_name = (col_profile.table_name or "").lower()
        col_name = col_profile.column_name.lower().replace(".", "_")

        # Bước 0.1: Kiểm tra bảng nhà cung cấp / tổ chức: tax_code là MST doanh nghiệp -> KEEP
        if tbl_name in ["suppliers", "vendor", "partners", "company"] and self._check_column_name(
            col_name, {"TAX_CODE": ["tax_code", "mst", "ma_so_thue"]}
        ):
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type="TAX_CODE_ORG",
                confidence=1.0,
                reasoning="Mã số thuế doanh nghiệp/tổ chức (công khai, không phải PII cá nhân).",
            )

        # Bước 0.4: Kiểm tra Free-text chứa PII nhúng (SĐT, Email, CCCD)
        if set(name_tokens(col_name)) & {"notes", "note", "body", "description", "comment", "message", "chu"}:
            phone_sub = re.compile(r"(0|84|\+84)[35789]\d{8}")
            cccd_sub = re.compile(r"\b\d{12}\b")
            email_sub = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
            for s in col_profile.samples:
                s_str = str(s)
                if phone_sub.search(s_str) or cccd_sub.search(s_str) or email_sub.search(s_str):
                    return FieldScanResult(
                        field_name=col_profile.column_name,
                        inferred_pii_type="FREE_TEXT_PII",
                        confidence=1.0,
                        reasoning="Trường văn bản tự do chứa thông tin PII nhúng (SĐT/CCCD/Email).",
                    )

        # Bước 1: Tên cột chắc chắn là PII (address, phone, fax, dob, email, tax_code, national_id...)
        high_conf = self._check_column_name(col_profile.column_name, HIGH_CONFIDENCE_COLUMNS)
        if high_conf:
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type=high_conf,
                confidence=1.0,
                reasoning=f"Matched high-confidence keyword for {high_conf}.",
            )

        # Bước 1.2: Cột tên "<thực thể>_name": first/contact/ship_name là họ tên người,
        # product/category_name là tên vật. Tên trống/mơ hồ (name, display_name) trả None.
        name_type = classify_name_column(col_profile.column_name)
        if name_type:
            is_person = name_type == "FULL_NAME"
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type=name_type,
                confidence=0.95,
                reasoning=(
                    "Tên gắn với một người (họ tên)." if is_person else "Tên của vật/tổ chức/địa danh, không phải người."
                ),
            )

        # Bước 2: Tên nghiệp vụ CỤ THỂ chắc chắn không phải PII (tracking_code, order_id, amount...).
        # Đứng trước regex nội dung vì mã vận đơn 12 số trùng định dạng CCCD.
        negative_type = self._check_column_name(col_profile.column_name, NEGATIVE_COLUMNS)
        if negative_type:
            return self._negative_result(col_profile, negative_type)

        # Bước 2.5: Cột rỗng (mọi giá trị NULL) - không có gì để chia sẻ, đề xuất loại bỏ.
        if not any(str(sample).strip() for sample in col_profile.samples):
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type="EMPTY_COLUMN",
                confidence=1.0,
                reasoning="Cột không có dữ liệu (toàn NULL): không cần chia sẻ.",
            )

        # Bước 2.6: Ngày/giờ sự kiện (đặt hàng, tuyển dụng, tạo...) - ngày sinh đã bị bắt ở Bước 1 theo tên.
        if _is_event_datetime(col_profile):
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type="NOT_PERSONAL_DATA",
                confidence=0.9,
                reasoning="Ngày/giờ sự kiện, không phải ngày sinh: không tự định danh được cá nhân.",
            )

        # Bước 3: Regex trên NỘI DUNG (khớp 100% mẫu) - trước luật khóa *_id chung chung,
        # để citizen_id / ref_id chứa CCCD, SĐT, email vẫn bị bắt.
        for pii_type in REGEX_PATTERNS.keys():
            match_ratio = self._check_samples_regex(pii_type, col_profile.samples)
            if match_ratio == 1.0 and len(col_profile.samples) > 0:
                return FieldScanResult(
                    field_name=col_profile.column_name,
                    inferred_pii_type=pii_type,
                    confidence=1.0,
                    reasoning=f"100% samples matched strict Regex for {pii_type}.",
                )

        # Bước 4: Khóa kỹ thuật *_id chung chung (product_id...). national_id, patient_id... bị loại trừ.
        if is_generic_id_column(col_profile.column_name):
            return self._negative_result(col_profile, "NOT_PERSONAL_DATA")

        return None
