"""Nạp mockup vào MongoDB để chạy thử: python -m mockup.load_mongo

Script này xóa rồi ghi lại collection, nên cố ý không đọc MONGO_URI (biến đó trỏ tới nguồn chỉ đọc).
Dùng --uri hoặc MOCKUP_MONGO_URI, mặc định là MongoDB trên máy. Từ chối chạy nếu database có collection lạ.
"""

import argparse
import os
import sys
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

DEFAULT_URI = "mongodb://admin:admin@localhost:27017/?authSource=admin"
DEFAULT_DATABASE = "mockup"

_BSON_OPTIONS = json_util.RELAXED_JSON_OPTIONS.with_options(tz_aware=True)


def load_mockup(client, database: str, data_dir: Path) -> dict[str, int]:
    """Thay nội dung các collection mockup, trả số document đã nạp của từng collection."""
    paths = sorted((data_dir / "mongo").glob("*.jsonl"))
    if not paths:
        raise FileNotFoundError(f"Chưa có mockup ở {data_dir}. Chạy: python -m mockup.generate")

    names = {path.stem for path in paths}
    unknown = sorted(set(client[database].list_collection_names()) - names)
    if unknown:
        raise ValueError(f"Database {database} có collection không thuộc mockup: {unknown}. Không nạp.")

    counts = {}
    for path in paths:
        with path.open(encoding="utf-8") as file:
            docs = [json_util.loads(line, json_options=_BSON_OPTIONS) for line in file]
        collection = client[database][path.stem]
        collection.drop()
        collection.insert_many(docs)
        counts[path.stem] = len(docs)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.getenv("MOCKUP_MONGO_URI", DEFAULT_URI))
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--data-dir", type=Path, default=Path("data/mockup"))
    args = parser.parse_args()

    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
    try:
        counts = load_mockup(client, args.database, args.data_dir)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(str(exc))
    finally:
        client.close()
    for name, count in counts.items():
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
