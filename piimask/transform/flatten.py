"""Tách document lồng nhau thành các bảng phẳng: dict làm phẳng thành cột, mảng tách thành bảng con."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

SCALAR_COLUMN = "value"


@dataclass(frozen=True)
class Row:
    """table rỗng là document gốc. key và parent_key là khóa thô, chỉ tồn tại trong bộ nhớ."""

    table: str
    key: str
    parent_key: str | None
    index: int | None
    fields: dict[str, Any]


def field_path(table: str, column: str) -> str:
    """Đường dẫn đầy đủ của cột, cùng cách viết với nhãn chuẩn: 'Batteries[].Serial'."""
    return f"{table}[].{column}" if table else column


def _flatten(item: dict, prefix: str, fields: dict[str, Any], arrays: list[tuple[str, list]]) -> None:
    for name, value in item.items():
        path = f"{prefix}{name}"
        if isinstance(value, dict) and value:
            _flatten(value, f"{path}.", fields, arrays)
        elif isinstance(value, list):
            arrays.append((path, value))
        else:
            fields[path] = value


def _rows(item: Any, table: str, key: str, parent_key: str | None, index: int | None) -> Iterator[Row]:
    fields: dict[str, Any] = {}
    arrays: list[tuple[str, list]] = []
    _flatten(item if isinstance(item, dict) else {SCALAR_COLUMN: item}, "", fields, arrays)
    yield Row(table, key, parent_key, index, fields)
    for path, items in arrays:
        for position, child in enumerate(items):
            yield from _rows(child, field_path(table, path), f"{key}/{path}[{position}]", key, position)


def split_document(document: dict, key: str) -> Iterator[Row]:
    """Dòng đầu là document gốc, các dòng sau là phần tử mảng, kể cả mảng nằm trong mảng."""
    yield from _rows(document, "", key, None, None)
