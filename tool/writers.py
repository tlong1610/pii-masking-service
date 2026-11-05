"""Ghi bảng đã che ra file. Ghi vào file .part rồi mới đổi tên, nên file đúng tên luôn là file đầy đủ."""

import csv
import math
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from bson import Decimal128
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

XLSX_MAX_ROWS = 1_048_576


def to_cell(value: Any) -> Any:
    """Đổi kiểu BSON sang kiểu file ghi được. Số không hữu hạn ghi thành chuỗi vì Excel không biểu diễn được."""
    if isinstance(value, Decimal128):
        value = value.to_decimal()
    if isinstance(value, float | Decimal):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
    if value is None or isinstance(value, bool | int | str):
        return value
    return str(value)


class _FileWriter:
    suffix = ""

    def __init__(self, path: Path):
        self.path = path
        self.part = path.with_name(f"{path.name}.part")

    def commit(self) -> None:
        self._finish()
        os.replace(self.part, self.path)

    def abort(self) -> None:
        self._close()
        self.part.unlink(missing_ok=True)

    def _finish(self) -> None:
        self._close()

    def _close(self) -> None:
        pass


class CsvWriter(_FileWriter):
    suffix = ".csv"

    def __init__(self, path: Path, columns: list[str]):
        super().__init__(path)
        # BOM để Excel đọc đúng tiếng Việt.
        self._file = self.part.open("w", encoding="utf-8-sig", newline="")
        self._csv = csv.writer(self._file)
        self._csv.writerow(columns)

    def write(self, values: list[Any]) -> None:
        cells = [to_cell(value) for value in values]
        self._csv.writerow([cell.isoformat() if isinstance(cell, datetime) else cell for cell in cells])

    def _close(self) -> None:
        self._file.close()


class XlsxWriter(_FileWriter):
    suffix = ".xlsx"

    def __init__(self, path: Path, columns: list[str]):
        super().__init__(path)
        self._book = Workbook(write_only=True)
        self._sheet = self._book.create_sheet("data")
        self._sheet.append(columns)
        self._rows = 1

    def _cell(self, value: Any) -> Any:
        cell = to_cell(value)
        if not isinstance(cell, str):
            return cell
        cell = ILLEGAL_CHARACTERS_RE.sub("", cell)
        if cell.startswith("="):
            # openpyxl coi chuỗi bắt đầu bằng dấu bằng là công thức.
            literal = WriteOnlyCell(self._sheet, cell)
            literal.data_type = "s"
            return literal
        return cell

    def write(self, values: list[Any]) -> None:
        self._rows += 1
        if self._rows > XLSX_MAX_ROWS:
            raise ValueError(f"Bảng vượt quá {XLSX_MAX_ROWS} dòng của XLSX, hãy xuất CSV")
        self._sheet.append([self._cell(value) for value in values])

    def _finish(self) -> None:
        self._book.save(self.part)

    def _close(self) -> None:
        self._sheet.close()


WRITERS = {"csv": CsvWriter, "xlsx": XlsxWriter}
