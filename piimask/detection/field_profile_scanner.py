import logging

from piimask.detection.regex_patterns import (
    HIGH_CONFIDENCE_COLUMNS,
    NEGATIVE_COLUMNS,
    classify_name_column,
    is_generic_id_column,
    match_column_keyword,
)
from piimask.detection.taxonomy import PII_TAXONOMY, PIIType
from piimask.schemas import FieldProfile, FieldScanProposal, PolicyAction

logger = logging.getLogger(__name__)

class FieldProfileScanner:
    """
    Scanner dành riêng cho Gate 2 (Enterprise).
    Không dùng dữ liệu thô (samples), chỉ dựa vào tên cột và statistics.
    """

    @staticmethod
    def flatten_path(path: str) -> str:
        """identity.cccd -> identity_cccd"""
        return path.replace(".", "_")

    def _check_column_name(self, path_snake: str, keyword_dict: dict) -> str | None:
        """Kiểm tra tên cột có chứa từ khóa (theo NGUYÊN TỪ, không phải chuỗi con)."""
        return match_column_keyword(path_snake, keyword_dict)

    def _check_statistics_heuristic(self, data_type: str, stats: dict, matched_type: str | None) -> str | None:
        """Dùng heuristic trên statistics để củng cố loại PII được phát hiện qua tên cột."""
        if not matched_type:
            return None

        max_len = stats.get("max_len")
        min_len = stats.get("min_len")

        if matched_type == PIIType.CCCD.value:
            # CCCD chuẩn ở VN có 12 số
            if max_len == 12 or min_len == 12:
                return PIIType.CCCD.value
            # Trả None để đánh dấu mập mờ, đẩy qua LLM
            return None

        if matched_type == PIIType.PHONE.value:
            # SĐT thường là string, độ dài 10-12
            if data_type == "string" and max_len in [10, 11, 12]:
                return PIIType.PHONE.value
            return matched_type  # Vẫn có thể là phone nhưng lưu dạng int...

        if matched_type == PIIType.TAX_CODE.value:
            if min_len and min_len >= 10:
                return PIIType.TAX_CODE.value

        if matched_type == PIIType.DOB.value:
            if data_type in ["date", "string"]:
                return PIIType.DOB.value

        return matched_type

    def get_classification_and_action(self, inferred_type: str) -> tuple[str, PolicyAction]:
        if inferred_type in [PIIType.TRACKING_CODE.value, PIIType.MONEY_ALONE.value, "NOT_PERSONAL_DATA"]:
            return ("NON_PERSONAL", PolicyAction.KEEP)

        tax_info = PII_TAXONOMY.get(inferred_type, {})
        classification = tax_info.get("classification", "PERSONAL_BASIC")

        action = PolicyAction.MASK
        if inferred_type == PIIType.CCCD.value:
            action = PolicyAction.HMAC

        return (classification, action)

    def scan(self, profile: FieldProfile) -> FieldScanProposal | None:
        """
        Quét dựa trên luật tĩnh (Tầng 1).
        Trả về None nếu mập mờ hoặc không có rule tĩnh nào xử lý được.
        """
        path_snake = self.flatten_path(profile.path)
        tbl_name = (profile.table_or_collection or "").lower()

        # Bước 0.1: Kiểm tra bảng nhà cung cấp / tổ chức: tax_code là MST doanh nghiệp -> KEEP
        if tbl_name in ["suppliers", "vendor", "partners", "company"] and self._check_column_name(
            path_snake, {"TAX_CODE": ["tax_code", "mst", "ma_so_thue"]}
        ):
            return FieldScanProposal(
                field_path=profile.path,
                classification="NON_PERSONAL",
                action=PolicyAction.KEEP,
                reason="Mã số thuế doanh nghiệp/tổ chức (công khai, không phải PII cá nhân).",
                confidence=1.0,
                tier="TIER_1_RULES"
            )

        # Bước 0.2: KYC Documents: ocr_text và file_path là tài liệu lưu trữ nhạy cảm -> DROP
        if tbl_name == "kyc_documents" and path_snake.lower() in ["ocr_text", "file_path"]:
            return FieldScanProposal(
                field_path=profile.path,
                classification="PERSONAL_SENSITIVE",
                action=PolicyAction.DROP,
                reason="Tài liệu/OCR giấy tờ tùy thân nhạy cảm trong bảng kyc_documents, loại bỏ khỏi view phân tích (DROP).",
                confidence=1.0,
                tier="TIER_1_RULES"
            )

        # Bước 1 & 2: Bắt PII rõ ràng qua tên cột + Statistics
        high_conf_type = self._check_column_name(path_snake, HIGH_CONFIDENCE_COLUMNS)
        if high_conf_type:
            validated_type = self._check_statistics_heuristic(profile.data_type, profile.statistics, high_conf_type)
            if validated_type:
                cls, act = self.get_classification_and_action(validated_type)
                return FieldScanProposal(
                    field_path=profile.path,
                    classification=cls,
                    action=act,
                    reason=f"Matched high-confidence keyword and verified via statistics for {validated_type}.",
                    confidence=0.95,
                    tier="TIER_1_RULES"
                )

        # Bước 2.5: Cột tên "<thực thể>_name" (first/contact_name -> họ tên; product_name -> không phải người)
        name_type = None if high_conf_type else classify_name_column(path_snake)
        if name_type:
            cls, act = self.get_classification_and_action(name_type)
            return FieldScanProposal(
                field_path=profile.path,
                classification=cls,
                action=act,
                reason=f"Name column classified by its entity as {name_type}. (Rules-based)",
                confidence=0.95,
                tier="TIER_1_RULES"
            )

        # Bước 3: Ca ÂM (Tracking, Order, Amount, khóa kỹ thuật *_id) - chỉ SAU khi đã loại trừ PII theo tên,
        # để national_id / patient_id không bao giờ bị coi là an toàn.
        negative_type = self._check_column_name(path_snake, NEGATIVE_COLUMNS)
        if negative_type is None and is_generic_id_column(path_snake):
            negative_type = "NOT_PERSONAL_DATA"
        # A PII-looking name whose statistics were inconclusive stays ambiguous (LLM), never "safe".
        if negative_type and not high_conf_type:
            cls, act = self.get_classification_and_action(negative_type)
            return FieldScanProposal(
                field_path=profile.path,
                classification=cls,
                action=act,
                reason=f"Matched negative keyword for {negative_type}. (Rules-based)",
                confidence=1.0,
                tier="TIER_1_RULES"
            )

        # Ca mập mờ (ví dụ có keyword nhưng max_len không khớp) hoặc không có keyword rõ ràng
        return None
