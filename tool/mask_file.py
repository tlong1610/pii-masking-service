"""Che một file và giữ nguyên cấu trúc: python -m tool.mask_file <vào> <ra>

Hỗ trợ CSV (giữ bảng mã, dấu phân cách, xuống dòng, tên cột, số dòng), .log (che theo dòng, giữ số dòng) và .gz chứa
log (nén lại). Đọc theo dòng, không nạp cả file. Excel, JSON, Parquet chưa hỗ trợ.
"""

import argparse
import codecs
import csv
import gzip
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from piimask.config import get_settings
from piimask.detection.rule_engine import RuleBasedScanner
from piimask.policy import FieldDecision, decide, undecided
from piimask.profile import FieldProfiler
from piimask.schemas import PolicyAction
from piimask.transform.mask_engine import apply_action, guard_value
from tool.export import require_secret

_DELIMITERS = ",;\t|"
_LOG_ENCODING = {"encoding": "utf-8", "errors": "surrogateescape", "newline": ""}


def detect_encoding(path: Path) -> str:
    with path.open("rb") as file:
        head = file.read(3)
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    return "utf-8-sig" if head.startswith(codecs.BOM_UTF8) else "utf-8"


def plan_columns(header: list[str], rows: Iterable[list[str]]) -> list[FieldDecision]:
    """Đọc hết các dòng để mẫu rải khắp file. Cột không có giá trị nào vẫn có quyết định."""
    profiler = FieldProfiler()
    profiler.add(dict.fromkeys(header))
    for row in rows:
        profiler.add(dict(zip(header, row, strict=False)))
    scanner = RuleBasedScanner()
    profiles = {profile.column_name: profile for profile in profiler.profiles()}
    return [decide(name, scanner.classify(profiles[name]), samples=profiles[name].samples) for name in header]


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
        decisions = plan_columns(header, reader)

    # Dòng có nhiều ô hơn tiêu đề: ô thừa chưa có quyết định nên bị che.
    extra = undecided("").action

    def mask_cell(position: int, cell: str) -> str:
        action = decisions[position].action if position < len(decisions) else extra
        if not cell:
            return cell
        if action == PolicyAction.KEEP.value:
            return guard_value(cell, decisions[position].guard_exempt)
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
