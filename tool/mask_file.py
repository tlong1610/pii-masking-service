"""Che một file và giữ nguyên cấu trúc: python -m tool.mask_file <vào> <ra>

Hỗ trợ CSV (giữ bảng mã, dấu phân cách, xuống dòng, tên cột, số dòng), .log (che theo dòng, giữ số dòng) và .gz chứa
log (nén lại). Đọc theo dòng, không nạp cả file. Excel, JSON, Parquet chưa hỗ trợ.
"""

import argparse
import codecs
import csv
import gzip
import itertools
import os
import sys
from collections.abc import Callable
from pathlib import Path

from piimask.config import get_settings
from piimask.detection.rule_engine import RuleBasedScanner
from piimask.policy import FieldDecision, decide, undecided
from piimask.schemas import ColumnProfile, PolicyAction
from piimask.transform.mask_engine import apply_action
from tool.export import require_secret

_SCAN_ROWS = 100
_SAMPLES = 5
_DELIMITERS = ",;\t|"
_LOG_ENCODING = {"encoding": "utf-8", "errors": "surrogateescape", "newline": ""}


def detect_encoding(path: Path) -> str:
    with path.open("rb") as file:
        head = file.read(3)
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    return "utf-8-sig" if head.startswith(codecs.BOM_UTF8) else "utf-8"


def _column_profile(name: str, values: list[str]) -> ColumnProfile:
    filled = [value for value in values if value.strip()]
    return ColumnProfile(
        column_name=name,
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=list(dict.fromkeys(filled))[:_SAMPLES],
    )


def plan_columns(header: list[str], rows: list[list[str]]) -> list[FieldDecision]:
    scanner = RuleBasedScanner()
    decisions = []
    for position, name in enumerate(header):
        profile = _column_profile(name, [row[position] for row in rows if position < len(row)])
        decisions.append(decide(name, scanner.tier1_static_filter(profile)))
    return decisions


def _replace_atomically(target: Path, write: Callable[[Path], None]) -> None:
    part = target.with_name(f"{target.name}.part")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write(part)
        os.replace(part, target)
    finally:
        part.unlink(missing_ok=True)


def mask_csv(source: Path, target: Path, *, secret: str, key_version: str) -> list[FieldDecision]:
    encoding = detect_encoding(source)
    with source.open(encoding=encoding, newline="") as file:
        first_line = file.readline()
    delimiter = max(_DELIMITERS, key=first_line.count)
    line_end = "\r\n" if first_line.endswith("\r\n") else "\n"

    with source.open(encoding=encoding, newline="") as file:
        reader = csv.reader(file, delimiter=delimiter)
        header = next(reader)
        decisions = plan_columns(header, list(itertools.islice(reader, _SCAN_ROWS)))

    # Dòng có nhiều ô hơn tiêu đề: ô thừa chưa có quyết định nên bị che.
    extra = undecided("").action

    def mask_cell(position: int, cell: str) -> str:
        action = decisions[position].action if position < len(decisions) else extra
        if not cell or action == PolicyAction.KEEP.value:
            return cell
        return apply_action(cell, action, secret=secret, key_version=key_version)[1]

    def write(part: Path) -> None:
        with source.open(encoding=encoding, newline="") as file, part.open("w", encoding=encoding, newline="") as out:
            reader = csv.reader(file, delimiter=delimiter)
            writer = csv.writer(out, delimiter=delimiter, lineterminator=line_end)
            writer.writerow(next(reader))
            for row in reader:
                writer.writerow([mask_cell(position, cell) for position, cell in enumerate(row)])

    _replace_atomically(target, write)
    return decisions


def _mask_line(line: str, secret: str, key_version: str) -> str:
    body = line.rstrip("\r\n")
    masked = apply_action(body, PolicyAction.REDACT.value, secret=secret, key_version=key_version)[1]
    return masked + line[len(body) :]


def mask_log(source: Path, target: Path, *, secret: str, key_version: str) -> None:
    packed = source.suffix == ".gz"

    def write(part: Path) -> None:
        reader = gzip.open(source, "rt", **_LOG_ENCODING) if packed else source.open(**_LOG_ENCODING)
        writer = gzip.open(part, "wt", **_LOG_ENCODING) if packed else part.open("w", **_LOG_ENCODING)
        with reader, writer:
            for line in reader:
                writer.write(_mask_line(line, secret, key_version))

    _replace_atomically(target, write)


def mask_file(source: Path, target: Path, *, secret: str, key_version: str) -> None:
    if source.resolve() == target.resolve():
        raise ValueError("File ra phải khác file vào")
    if source.suffix == ".csv":
        mask_csv(source, target, secret=secret, key_version=key_version)
    elif source.suffix in (".log", ".gz"):
        mask_log(source, target, secret=secret, key_version=key_version)
    else:
        raise ValueError(f"Chưa hỗ trợ định dạng {source.suffix}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--allow-dev-secret", action="store_true", help="chỉ dùng khi dev")
    args = parser.parse_args()

    settings = get_settings()
    require_secret(settings, args.allow_dev_secret)
    try:
        mask_file(args.source, args.target, secret=settings.hmac_secret, key_version=settings.hmac_key_version)
    except ValueError as exc:
        sys.exit(str(exc))
    except Exception as exc:
        sys.exit(f"Che file thất bại: {type(exc).__name__}")


if __name__ == "__main__":
    main()
