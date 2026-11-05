"""Quét MongoDB, áp chính sách, xuất CSV và XLSX đã che: python -m tool.export

Mỗi collection ra một file, mỗi mảng ra một file con có khóa cha đã HMAC. Đọc hai lượt theo lô: lượt đầu lấy
đủ bộ cột của schema không cố định, lượt sau che và ghi. Trường chưa có kết luận bị che toàn bộ. report.json ghi
hành động của từng trường, không chứa giá trị.
"""

import argparse
import json
import logging
import re
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pymongo import MongoClient

from piimask.config import DEV_HMAC_SECRET, Settings, get_settings
from piimask.connectors.mongo_connector import MongoConnector
from piimask.detection.rule_engine import RuleBasedScanner
from piimask.policy import FieldDecision, decide, undecided
from piimask.schemas import PolicyAction
from piimask.transform.flatten import Row, field_path, split_document
from piimask.transform.hmac_hasher import hash_value, normalize_for_hmac
from piimask.transform.mask_engine import apply_action
from tool.writers import WRITERS

logger = logging.getLogger(__name__)

_ID_FIELD = "_id"
_LINK_COLUMNS = ["_parent_key", "_row_key", "_index"]
_UNSAFE_NAME = re.compile(r"[^\w.-]+")


def build_plans(connector: MongoConnector, join_keys: frozenset[str]) -> dict[str, dict[str, FieldDecision]]:
    """Quyết định theo trường cho từng collection. _id luôn HMAC vì file con nối về nó."""
    scanner = RuleBasedScanner()
    plans: dict[str, dict[str, FieldDecision]] = {}
    for task in connector.to_scanner_contract():
        path = task["field_path"]
        result = scanner.tier1_static_filter(task["column_profile"])
        plans.setdefault(task["collection_name"], {})[path] = decide(path, result, join_keys)
    for plan in plans.values():
        plan[_ID_FIELD] = FieldDecision(_ID_FIELD, None, None, PolicyAction.HMAC.value, "khoa_chinh")
    return plans


def discover_columns(documents: Iterable[dict]) -> dict[str, list[str]]:
    """Bộ cột của từng bảng theo thứ tự gặp. Chỉ giữ tên cột, không giữ giá trị."""
    tables: dict[str, dict[str, None]] = {}
    for document in documents:
        for row in split_document(document, ""):
            tables.setdefault(row.table, {}).update(dict.fromkeys(row.fields))
    return {table: list(columns) for table, columns in tables.items()}


def table_file_name(collection: str, table: str) -> str:
    name = f"{collection}__{table.replace('[].', '__')}" if table else collection
    return _UNSAFE_NAME.sub("_", name)


class _Table:
    """Một bảng đầu ra: quyết định cho từng cột và các file đang ghi."""

    def __init__(self, table: str, columns: list[str], plan: dict[str, FieldDecision], base_path: Path, formats):
        self.table = table
        self.columns = columns
        self.decisions = {}
        for column in columns:
            path = field_path(table, column)
            self.decisions[column] = plan.get(path) or undecided(path, "ngoai_pham_vi_quet")
        self.header = columns if not table else _LINK_COLUMNS + columns
        self.writers = []
        for name in formats:
            writer_class = WRITERS[name]
            self.writers.append(writer_class(base_path.with_name(base_path.name + writer_class.suffix), self.header))
        self.rows = 0

    def write(self, row: Row, secret: str, key_version: str) -> None:
        values: list[Any] = []
        if self.table:
            values += [
                hash_value(row.parent_key, secret=secret, key_version=key_version),
                hash_value(row.key, secret=secret, key_version=key_version),
                row.index,
            ]
        for column in self.columns:
            action = self.decisions[column].action
            values.append(apply_action(row.fields.get(column), action, secret=secret, key_version=key_version)[1])
        for writer in self.writers:
            writer.write(values)
        self.rows += 1


def export_collection(
    connector: MongoConnector,
    collection: str,
    plan: dict[str, FieldDecision],
    out_dir: Path,
    formats: list[str],
    *,
    secret: str,
    key_version: str,
    batch_size: int,
) -> dict:
    started = time.perf_counter()
    columns = discover_columns(connector.iter_documents(collection, batch_size))
    tables = {
        table: _Table(table, names, plan, out_dir / table_file_name(collection, table), formats)
        for table, names in columns.items()
    }
    writers = [writer for table in tables.values() for writer in table.writers]

    documents = 0
    try:
        for document in connector.iter_documents(collection, batch_size):
            documents += 1
            for row in split_document(document, normalize_for_hmac(document[_ID_FIELD])):
                # Bảng xuất hiện sau lượt đọc đầu thì bỏ qua: không ghi còn hơn ghi vào cột chưa được quyết định.
                if row.table in tables:
                    tables[row.table].write(row, secret, key_version)
        for writer in writers:
            writer.commit()
    except BaseException:
        for writer in writers:
            writer.abort()
        raise

    return {
        "documents": documents,
        "rows": {table.table or collection: table.rows for table in tables.values()},
        "files": sorted(writer.path.name for writer in writers),
        "fields": [decision.to_dict() for table in tables.values() for decision in table.decisions.values()],
        "seconds": round(time.perf_counter() - started, 3),
    }


def export_database(
    connector: MongoConnector,
    out_dir: Path,
    *,
    secret: str,
    key_version: str,
    formats: list[str] | None = None,
    join_keys: Iterable[str] = (),
    collections: list[str] | None = None,
    batch_size: int = 1000,
) -> dict:
    """Xuất các collection vào out_dir, ghi report.json và trả nội dung của nó."""
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    plans = build_plans(connector, frozenset(name.lower() for name in join_keys))
    scan_seconds = time.perf_counter() - started

    report: dict[str, Any] = {
        "engine": "mongodb",
        "database": connector.database_name,
        "hmac_key_version": key_version,
        "scan_seconds": round(scan_seconds, 3),
        "collections": {},
    }
    for name, plan in sorted(plans.items()):
        if collections is not None and name not in collections:
            continue
        report["collections"][name] = export_collection(
            connector,
            name,
            plan,
            out_dir,
            formats or list(WRITERS),
            secret=secret,
            key_version=key_version,
            batch_size=batch_size,
        )
        logger.info("Đã xuất %s: %d document", name, report["collections"][name]["documents"])

    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def require_secret(settings: Settings, allow_dev_secret: bool) -> None:
    if not settings.hmac_secret or (settings.hmac_secret == DEV_HMAC_SECRET and not allow_dev_secret):
        sys.exit("Chưa đặt HMAC_SECRET. Sinh bằng: openssl rand -hex 32")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default=settings.mongo_db)
    parser.add_argument("--collection", action="append", help="chỉ xuất collection này, lặp lại được")
    parser.add_argument("--out", type=Path, default=Path("data/export"))
    parser.add_argument("--format", action="append", choices=sorted(WRITERS), help="mặc định xuất cả CSV và XLSX")
    parser.add_argument("--join-key", action="append", default=[], help="trường dùng để nối bảng, CCCD ở đó dùng HMAC")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--allow-dev-secret", action="store_true", help="chỉ dùng khi dev")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    require_secret(settings, args.allow_dev_secret)

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    connector = MongoConnector(settings.mongo_uri, database_name=args.database, client=client)
    try:
        report = export_database(
            connector,
            args.out,
            secret=settings.hmac_secret,
            key_version=settings.hmac_key_version,
            formats=args.format,
            join_keys=args.join_key,
            collections=args.collection,
            batch_size=args.batch_size,
        )
    except Exception as exc:
        # Thông báo lỗi của driver có thể chứa URI hoặc giá trị nên chỉ in loại lỗi.
        sys.exit(f"Xuất thất bại: {type(exc).__name__}")
    finally:
        client.close()

    if not report["collections"]:
        sys.exit(f"Không có collection nào để xuất trong database {args.database}")
    print(f"Đã xuất {len(report['collections'])} collection vào {args.out}")


if __name__ == "__main__":
    main()
