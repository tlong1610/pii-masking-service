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
from piimask.detection.taxonomy import PIIType
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
    Lớp Lọc 1: Rule-Based & Regex Scanner.
    Nhiệm vụ: Chặn ngay lập tức các PII rõ ràng (như CCCD, Email, Phone)
    hoặc bỏ qua các loại chắc chắn không phải PII (Mã vận đơn, số tiền).
    Những thứ không chắc chắn (UNKNOWN) sẽ được đẩy qua các lớp sau (LLM, DPO).
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

    def _get_recommended_action(self, inferred_type: str, enforced_action: str | None) -> str:
        """Helper để map loại PII với action nếu chưa có enforced_action."""
        if enforced_action:
            return enforced_action

        # CCCD / Join Key: Luôn dùng HMAC để bảo toàn khóa nối quan hệ downstream
        if inferred_type == PIIType.CCCD.value:
            return "HMAC"

        # Nếu là loại không phải dữ liệu cá nhân, hoặc định danh gián tiếp cần cho phân tích (thành phố) -> KEEP
        if inferred_type in [
            PIIType.TRACKING_CODE.value, PIIType.MONEY_ALONE.value, "NOT_PERSONAL_DATA", "TAX_CODE_ORG", "CITY"
        ]:
            return "KEEP"

        # Nếu là UNKNOWN -> KEEP (để pass qua LLM quyết định)
        if inferred_type == PIIType.UNKNOWN.value:
            return "KEEP"

        return "MASK"

    def _negative_result(
        self, col_profile: ColumnProfile, negative_type: str, enforced_action: str | None
    ) -> FieldScanResult:
        return FieldScanResult(
            field_name=col_profile.column_name,
            inferred_pii_type=negative_type,
            confidence=1.0,
            recommended_action=self._get_recommended_action(negative_type, enforced_action),
            reasoning=f"Matched negative keyword for {negative_type}; no PII pattern in name or samples.",
            tier="TIER_1",
        )

    def tier1_static_filter(self, col_profile: ColumnProfile) -> FieldScanResult | None:
        """
        Tầng 1 (Cascade Funnel): Lọc tĩnh (Rule-based & Regex).
        Chỉ trả về kết quả nếu khớp 100% (chắc chắn PII hoặc chắc chắn KHÔNG phải).
        Nếu mập mờ (không khớp 100%), trả về None để đẩy xuống Tầng 2.
        """
        enforced_action = col_profile.system_recommendation
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
                recommended_action="KEEP",
                reasoning="Mã số thuế doanh nghiệp/tổ chức (công khai, không phải PII cá nhân).",
                tier="TIER_1"
            )

        # Bước 0.2: KYC Documents: ocr_text và file_path là tài liệu lưu trữ nhạy cảm -> DROP
        if tbl_name == "kyc_documents" and col_name in ["ocr_text", "file_path"]:
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type="OCR_IDENTITY_DOC" if col_name == "ocr_text" else "INTERNAL_FILE_PATH",
                confidence=1.0,
                recommended_action="DROP",
                reasoning="Tài liệu/OCR giấy tờ tùy thân nhạy cảm trong bảng kyc_documents, loại bỏ khỏi view phân tích (DROP).",
                tier="TIER_1"
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
                        recommended_action="MASK",
                        reasoning="Trường văn bản tự do chứa thông tin PII nhúng (SĐT/CCCD/Email).",
                        tier="TIER_1"
                    )

        # Bước 1: Tên cột chắc chắn là PII (address, phone, fax, dob, email, tax_code, national_id...)
        high_conf = self._check_column_name(col_profile.column_name, HIGH_CONFIDENCE_COLUMNS)
        if high_conf:
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type=high_conf,
                confidence=1.0,
                recommended_action=self._get_recommended_action(high_conf, enforced_action),
                reasoning=f"Matched high-confidence keyword for {high_conf}.",
                tier="TIER_1"
            )

        # Bước 1.2: Cột tên "<thực thể>_name": first/contact/ship_name là họ tên người,
        # product/category_name là tên vật. Tên trống/mơ hồ (name, display_name) để LLM xét.
        name_type = classify_name_column(col_profile.column_name)
        if name_type:
            is_person = name_type == "FULL_NAME"
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type=name_type,
                confidence=0.95,
                recommended_action=self._get_recommended_action(name_type, enforced_action),
                reasoning=(
                    "Tên gắn với một người (họ tên)." if is_person else "Tên của vật/tổ chức/địa danh, không phải người."
                ),
                tier="TIER_1",
            )

        # Bước 2: Tên nghiệp vụ CỤ THỂ chắc chắn không phải PII (tracking_code, order_id, amount...).
        # Đứng trước regex nội dung vì mã vận đơn 12 số trùng định dạng CCCD.
        negative_type = self._check_column_name(col_profile.column_name, NEGATIVE_COLUMNS)
        if negative_type:
            return self._negative_result(col_profile, negative_type, enforced_action)

        # Bước 2.5: Cột rỗng (mọi giá trị NULL) - không có gì để chia sẻ, đề xuất loại bỏ.
        if not any(str(sample).strip() for sample in col_profile.samples):
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type="EMPTY_COLUMN",
                confidence=1.0,
                recommended_action=enforced_action or "DROP",
                reasoning="Cột không có dữ liệu (toàn NULL): không cần chia sẻ.",
                tier="TIER_1",
            )

        # Bước 2.6: Ngày/giờ sự kiện (đặt hàng, tuyển dụng, tạo...) - ngày sinh đã bị bắt ở Bước 1 theo tên.
        if _is_event_datetime(col_profile):
            return FieldScanResult(
                field_name=col_profile.column_name,
                inferred_pii_type="NOT_PERSONAL_DATA",
                confidence=0.9,
                recommended_action=self._get_recommended_action("NOT_PERSONAL_DATA", enforced_action),
                reasoning="Ngày/giờ sự kiện, không phải ngày sinh: không tự định danh được cá nhân.",
                tier="TIER_1",
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
                    recommended_action=self._get_recommended_action(pii_type, enforced_action),
                    reasoning=f"100% samples matched strict Regex for {pii_type}.",
                    tier="TIER_1"
                )

        # Bước 4: Khóa kỹ thuật *_id chung chung (product_id...). national_id, patient_id... bị loại trừ.
        if is_generic_id_column(col_profile.column_name):
            return self._negative_result(col_profile, "NOT_PERSONAL_DATA", enforced_action)

        # Mập mờ -> Trả về None để đẩy xuống Tầng 2 (BM25)
        return None

    @staticmethod
    def transform_to_data_shape(samples: list[str]) -> list[str]:
        """
        Helper cho Tầng 3: Biến đổi dữ liệu thô thành Data Shape ẩn danh.
        VD: '0901234567' -> 'XXXXXXXXXX', 'nguyen@gmail.com' -> 'XXXXXX@XXXXX.XXX'
        """
        shapes = []
        for sample in samples:
            if not sample:
                continue
            shape_str = ""
            for char in str(sample):
                if char.isdigit():
                    shape_str += "X"
                elif char.isalpha():
                    shape_str += "C"  # C for Character
                else:
                    shape_str += char # Giữ lại các ký tự đặc biệt như @, -, .
            shapes.append(shape_str)
        return shapes
