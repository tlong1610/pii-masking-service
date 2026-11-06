"""Kiểu dữ liệu dùng chung của lõi piimask. Không chứa giá trị PII thô."""

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):  # noqa: UP042
        pass

from pydantic import BaseModel, Field


class PolicyAction(StrEnum):
    MASK = "MASK"
    PARTIAL = "PARTIAL"
    HMAC = "HMAC"
    REDACT = "REDACT"
    DROP = "DROP"
    NULLIFY = "NULLIFY"
    KEEP = "KEEP"


class ColumnProfile(BaseModel):
    table_name: str | None = Field(default=None, description="Tên bảng hoặc collection")
    column_name: str = Field(..., description="Tên cột")
    data_type: str = Field(..., description="Kiểu dữ liệu SQL")
    is_primary_key: bool = Field(..., description="Có phải khóa chính không")
    is_foreign_key: bool = Field(..., description="Có phải khóa ngoại không")
    samples: list[str] = Field(
        ...,
        description="Dữ liệu mẫu ngắn hạn chỉ xử lý trong bộ nhớ (In-memory ephemeral samples)",
    )
    system_recommendation: str | None = Field(
        default=None, description="Gợi ý cứng của hệ thống (ví dụ: HASHING cho KEY)"
    )


class TableRelation(BaseModel):
    from_column: str = Field(..., description="Cột khóa ngoại ở bảng hiện tại")
    to_table: str = Field(..., description="Bảng đích mà khóa ngoại trỏ tới")
    to_column: str = Field(..., description="Cột đích ở bảng đích")


class TableProfile(BaseModel):
    table_name: str = Field(..., description="Tên bảng")
    relations: list[TableRelation] = Field(..., description="Danh sách quan hệ khóa ngoại")
    columns: list[ColumnProfile] = Field(..., description="Profile của các cột trong bảng")


class DatabaseProfile(BaseModel):
    database_name: str = Field(..., description="Tên CSDL")
    tables: list[TableProfile] = Field(..., description="Danh sách cấu trúc các bảng")


# --- Schema cho kết quả quét PII (Output của Scanner / LLM) ---

class FieldScanResult(BaseModel):
    field_name: str = Field(..., description="Tên cột đã phân tích")
    inferred_pii_type: str = Field(
        ..., description="Loại PII phát hiện (Ví dụ: CCCD, PHONE, EMAIL, UNKNOWN)"
    )
    confidence: float = Field(..., description="Độ tin cậy (0.0 đến 1.0)")
    recommended_action: str = Field(..., description="Hành động gợi ý: MASK, DROP, HMAC, KEEP")
    reasoning: str = Field(..., description="Lý do hoặc căn cứ quyết định")

    # Các trường mở rộng cho mô hình Phễu lọc 3 tầng
    tier: str = Field(default="", description="Tầng ra quyết định (TIER_1, TIER_2, TIER_3)")
    bm25_score: float | None = Field(default=None, description="Điểm tần suất từ khóa BM25 (Tầng 2)")
    hybrid_score: float | None = Field(default=None, description="Điểm hỗn hợp Hybrid (Tầng 3.1)")
    confidence_score: float | None = Field(default=None, description="Điểm tin cậy của tier (BM25 normalized, hybrid fusion, hoặc LLM softmax)")
    provider_meta: dict | None = Field(default=None, description="LLM provider metadata (usage/model), no data")

# --- Schema cho Luồng Enterprise (Gate 2 - Không chứa raw PII) ---

class FieldProfile(BaseModel):
    """Profile của một trường đã được lọc — không chứa raw sample_value."""
    engine: str = Field(..., description='"postgresql" hoặc "mongodb"')
    table_or_collection: str = Field(..., description="Tên bảng hoặc collection")
    path: str = Field(..., description="Đường dẫn trường (VD: 'cccd' hoặc 'identity.cccd')")
    data_type: str = Field(..., description="Kiểu dữ liệu (VD: 'string', 'integer')")
    null_count: int = Field(default=0, description="Số lượng giá trị null")
    distinct_count: int = Field(default=0, description="Số lượng giá trị unique")
    statistics: dict = Field(
        default_factory=dict,
        description="Thống kê đã làm sạch (VD: {'min_len': 12, 'max_len': 12, 'pattern': 'XXX'})"
    )
    samples: list[str] = Field(
        default_factory=list,
        description="Dữ liệu mẫu đã che/khử nhận dạng (Masked/Sanitized samples - KHÔNG chứa raw PII)",
    )

class FieldScanProposal(BaseModel):
    """Kết quả scan trả về cho luồng Enterprise."""
    field_path: str = Field(..., description="Đường dẫn trường (khớp với input)")
    classification: str = Field(..., description="Phân loại (VD: PERSONAL_SENSITIVE, NON_PERSONAL)")
    action: PolicyAction = Field(..., description="Hành động đề xuất (MASK, HMAC, KEEP, DROP)")
    reason: str = Field(..., description="Lý do đề xuất")
    confidence: float = Field(..., description="Độ tự tin (0.0 - 1.0)")
    tier: str = Field(..., description="Tầng ra quyết định (VD: TIER_1_RULES, TIER_3_LLM)")
    provider_meta: dict | None = Field(default=None, description="Metadata bổ sung từ LLM/Scanner")


# --- Schema cho Audit Log Hash-Chain (FR-11, §14.3) ---
