"""Kiểu dữ liệu dùng chung của lõi piimask. Không chứa giá trị PII thô."""

from enum import StrEnum

from pydantic import BaseModel, Field


class PolicyAction(StrEnum):
    MASK = "MASK"
    PARTIAL = "PARTIAL"
    HMAC = "HMAC"
    REDACT = "REDACT"
    DROP = "DROP"
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


class FieldScanResult(BaseModel):
    field_name: str = Field(..., description="Tên cột đã phân tích")
    inferred_pii_type: str = Field(..., description="Loại PII phát hiện (Ví dụ: CCCD, PHONE, EMAIL)")
    confidence: float = Field(..., description="Độ tin cậy (0.0 đến 1.0)")
    reasoning: str = Field(..., description="Lý do hoặc căn cứ quyết định")
