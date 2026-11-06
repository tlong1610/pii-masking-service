"""Lập profile trường từ một luồng bản ghi, không phụ thuộc nguồn dữ liệu.

Đọc hết nguồn nên liệt kê đủ mọi trường, kể cả trường chỉ có ở vài bản ghi cuối, trong mảng hay lồng sâu. Mẫu lấy bằng
reservoir sampling nên rải đều cả nguồn, không dồn vào các bản ghi đầu. Mẫu chỉ ở trong bộ nhớ.
"""

import random
from datetime import date, datetime
from typing import Any

from piimask.schemas import ColumnProfile
from piimask.transform.flatten import field_path, split_document

SAMPLE_SIZE = 50


def infer_data_type(value: Any) -> str:
    """Tên kiểu rút gọn của một giá trị Python hoặc BSON."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime | date):
        return "date"
    if isinstance(value, dict):
        return "object"
    return "string"


class _Field:
    __slots__ = ("data_type", "seen", "samples")

    def __init__(self) -> None:
        self.data_type: str | None = None
        self.seen = 0
        self.samples: list[str] = []


class FieldProfiler:
    def __init__(self, table_name: str | None = None, sample_size: int = SAMPLE_SIZE, seed: int = 0):
        self.table_name = table_name
        self.sample_size = sample_size
        self._rng = random.Random(f"{table_name}/{seed}")
        self._fields: dict[str, _Field] = {}

    def add(self, record: dict) -> None:
        for row in split_document(record, ""):
            for column, value in row.fields.items():
                path = field_path(row.table, column)
                field = self._fields.get(path)
                if field is None:
                    field = self._fields[path] = _Field()
                if value is not None:
                    self._add_value(field, value)

    def _add_value(self, field: _Field, value: Any) -> None:
        if field.data_type is None:
            field.data_type = infer_data_type(value)
        text = str(value).strip()
        if not text:
            return
        field.seen += 1
        if len(field.samples) < self.sample_size:
            field.samples.append(text)
        else:
            position = self._rng.randrange(field.seen)
            if position < self.sample_size:
                field.samples[position] = text

    def profiles(self) -> list[ColumnProfile]:
        return [
            ColumnProfile(
                table_name=self.table_name,
                column_name=path,
                data_type=field.data_type or "string",
                is_primary_key=path == "_id",
                is_foreign_key=False,
                samples=field.samples,
            )
            for path, field in self._fields.items()
        ]
