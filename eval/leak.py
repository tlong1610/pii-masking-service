"""Đếm giá trị PII gốc còn sót trong file đã che.

Lấy giá trị gốc của mọi trường có nhãn từ nguồn, rồi dò trong toàn bộ file đã che, không phân biệt cột. Giá trị gốc chỉ
ở trong bộ nhớ, kết quả chỉ có số đếm.
"""

import json
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

from flashtext import KeywordProcessor
from openpyxl import load_workbook

from piimask.transform.flatten import field_path, split_document


def pii_labels(labels: list[dict], collection: str) -> dict[str, dict]:
    """Trường có nhãn PII của một collection. Văn bản tự do đo riêng theo thực thể nên không tính ở đây."""
    return {
        label["path"]: label
        for label in labels
        if label["collection"] == collection and label["pii_type"] not in (None, "FREE_TEXT")
    }


def load_labels(path: Path, collection: str) -> dict[str, dict]:
    with path.open(encoding="utf-8") as file:
        return pii_labels([json.loads(line) for line in file], collection)


def collect_values(documents: Iterable[dict], labels: dict[str, dict]) -> tuple[dict[str, str], Counter, set[str]]:
    """Trả giá trị gốc -> loại PII, số lần xuất hiện ở nguồn theo loại, và giá trị của khách doanh nghiệp được phép giữ.

    Bỏ giá trị rỗng. Mã của khách doanh nghiệp có thể gặp ở collection không có cờ, bên gọi loại nó khỏi phép dò.
    """
    values: dict[str, str] = {}
    totals: Counter = Counter()
    allowed: set[str] = set()
    for document in documents:
        for row in split_document(document, ""):
            for column, value in row.fields.items():
                label = labels.get(field_path(row.table, column))
                if label is None or value in (None, ""):
                    continue
                condition = label.get("when")
                if condition and document.get(condition["field"]) != condition["equals"]:
                    allowed.add(str(value))
                    continue
                values[str(value)] = label["pii_type"]
                totals[label["pii_type"]] += 1
    return values, totals, allowed


def _csv_lines(path: Path) -> Iterator[str]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        yield from file


def _xlsx_lines(path: Path) -> Iterator[str]:
    book = load_workbook(path, read_only=True)
    try:
        for sheet in book.worksheets:
            for row in sheet.iter_rows(values_only=True):
                yield "\t".join("" if cell is None else str(cell) for cell in row)
    finally:
        book.close()


def build_matcher(values: dict[str, str]) -> KeywordProcessor:
    """Khớp nguyên giá trị: chuỗi số nằm giữa một digest HMAC không bị tính nhầm."""
    matcher = KeywordProcessor(case_sensitive=True)
    for value, key in values.items():
        matcher.add_keyword(value, key)
    return matcher


def count_in_lines(matcher: KeywordProcessor, lines: Iterable[str]) -> Counter:
    found: Counter = Counter()
    for line in lines:
        found.update(matcher.extract_keywords(line))
    return found


def scan_output(out_dir: Path, values: dict[str, str]) -> dict[str, Counter]:
    """Số lần giá trị gốc còn xuất hiện trong từng định dạng, theo khóa của giá trị."""
    matcher = build_matcher(values)
    readers = {"csv": _csv_lines, "xlsx": _xlsx_lines}
    result = {}
    for name, read in readers.items():
        found: Counter = Counter()
        for path in sorted(out_dir.glob(f"*.{name}")):
            found += count_in_lines(matcher, read(path))
        result[name] = found
    return result
