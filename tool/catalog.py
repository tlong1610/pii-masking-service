"""Sinh danh mục trường PII: python -m tool.catalog

Mỗi collection một file JSON theo docs/api/pii-catalog-v1.schema.json. Liệt kê mọi trường để bên lọc phân biệt được trường
đã xét với trường mới. Không chứa giá trị. Đọc bằng tài khoản chỉ đọc, không cần khóa HMAC.
"""

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pymongo import MongoClient

from piimask import __version__
from piimask.config import get_settings
from piimask.connectors.mongo_connector import MongoConnector
from piimask.policy import FieldDecision
from tool.export import build_plans, table_file_name

SCHEMA_VERSION = 1


def catalog_field(decision: FieldDecision) -> dict:
    field = {
        "path": decision.path,
        "pii_type": decision.pii_type,
        "group": decision.group,
        "action": decision.action,
        "confidence": decision.confidence,
        "reason": decision.reason,
    }
    if decision.enterprise_flag:
        field["when"] = {"field": decision.enterprise_flag, "equals": False}
    return field


def build_catalogs(
    connector: MongoConnector,
    join_keys: frozenset[str] = frozenset(),
    collections: list[str] | None = None,
    enterprise_flag: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, dict]:
    """Danh mục của từng collection, trường sắp theo đường dẫn để so sánh được giữa hai lần sinh."""
    plans = build_plans(connector, join_keys, collections, enterprise_flag=enterprise_flag)
    stamp = (generated_at or datetime.now(UTC)).isoformat()
    return {
        name: {
            "schemaVersion": SCHEMA_VERSION,
            "engine": "mongodb",
            "database": connector.database_name,
            "collection": name,
            "generatedAt": stamp,
            "maskerVersion": __version__,
            "fields": [catalog_field(plan[path]) for path in sorted(plan)],
        }
        for name, plan in plans.items()
    }


def write_catalogs(catalogs: dict[str, dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, catalog in sorted(catalogs.items()):
        path = out_dir / f"{table_file_name(name, '')}.json"
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: Iterable[str] | None = None) -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default=settings.mongo_db)
    parser.add_argument("--collection", action="append", help="chỉ sinh cho collection này, lặp lại được")
    parser.add_argument("--out", type=Path, default=Path("data/catalog"))
    parser.add_argument("--join-key", action="append", default=[], help="trường dùng để nối bảng, CCCD ở đó dùng HMAC")
    args = parser.parse_args(argv)

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    connector = MongoConnector(settings.mongo_uri, database_name=args.database, client=client)
    try:
        catalogs = build_catalogs(
            connector,
            frozenset(name.lower() for name in args.join_key),
            args.collection,
            settings.enterprise_flag_field,
        )
    except Exception as exc:
        # Thông báo lỗi của driver có thể chứa URI hoặc giá trị nên chỉ in loại lỗi.
        sys.exit(f"Sinh danh mục thất bại: {type(exc).__name__}")
    finally:
        client.close()

    if not catalogs:
        sys.exit(f"Không có collection nào trong database {args.database}")
    print(f"Đã sinh {len(write_catalogs(catalogs, args.out))} danh mục vào {args.out}")


if __name__ == "__main__":
    main()
