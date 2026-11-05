"""Đo tốc độ quét và che trên collection lớn: python -m eval.perf --update-baseline

Cần MongoDB đang chạy và đã nạp mockup.load_perf. Đọc bằng MONGO_URI (tài khoản chỉ đọc). Số đo phụ thuộc máy chạy,
báo cáo ghi kèm số CPU. File xuất ghi vào thư mục tạm rồi xóa. Có --api-url thì đo thêm độ trễ API.
"""

import argparse
import json
import os
import resource
import statistics
import tempfile
import time
from pathlib import Path

import httpx
from pymongo import MongoClient

from eval.run import _commit
from mockup.load_perf import PERF_COLLECTION, perf_database
from piimask.config import get_settings
from piimask.connectors.mongo_connector import MongoConnector
from tool.export import export_database

_REPO = Path(__file__).resolve().parent.parent
_DEV_SECRET = "chi-dung-de-do-toc-do"
_API_SAMPLE = (
    "Khách gọi 0912345678, email demo.kh@example.com, CCCD 001099012345, hẹn gặp tại trạm sạc số 12 lúc 9 giờ sáng. "
    "Mã vận đơn và số tiền giữ nguyên để đối soát."
)


def measure_export(connector: MongoConnector, formats: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as out_dir:
        started = time.perf_counter()
        report = export_database(
            connector,
            Path(out_dir),
            secret=_DEV_SECRET,
            key_version="perf",
            formats=formats,
            join_keys=["IdNumber"],
            collections=[PERF_COLLECTION],
        )
        seconds = time.perf_counter() - started
    result = report["collections"][PERF_COLLECTION]
    rows = sum(result["rows"].values())
    return {
        "formats": formats,
        "documents": result["documents"],
        "rows_written": rows,
        "scan_seconds": report["scan_seconds"],
        "total_seconds": round(seconds, 2),
        "documents_per_second": round(result["documents"] / seconds),
        "rows_per_second": round(rows / seconds),
    }


def measure_api(url: str, requests: int = 500) -> dict:
    body = {"schemaVersion": 1, "requestId": "perf", "context": "ticket", "locale": "vi", "text": _API_SAMPLE}
    timings = []
    with httpx.Client(base_url=url, timeout=5) as client:
        for _ in range(requests):
            started = time.perf_counter()
            client.post("/v1/mask/text", json=body).raise_for_status()
            timings.append((time.perf_counter() - started) * 1000)
    percentiles = statistics.quantiles(timings, n=100)
    return {
        "requests": requests,
        "text_chars": len(_API_SAMPLE),
        "p50_ms": round(percentiles[49], 2),
        "p95_ms": round(percentiles[94], 2),
    }


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=perf_database(settings.mongo_db))
    parser.add_argument("--api-url")
    parser.add_argument("--baseline", type=Path, default=_REPO / "eval/results/baseline.json")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args()

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
    connector = MongoConnector(settings.mongo_uri, database_name=args.database, client=client)
    try:
        report = {
            "data_source": "mockup, chỉ đo tốc độ",
            "commit": _commit(),
            "cpu_count": os.cpu_count(),
            "detector": "regex + quy tắc, GLiNER tắt",
            "csv": measure_export(connector, ["csv"]),
            "csv_xlsx": measure_export(connector, ["csv", "xlsx"]),
            "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        }
    finally:
        client.close()
    if args.api_url:
        report["api"] = measure_api(args.api_url)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.update_baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        baseline["performance_large"] = report
        args.baseline.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Đã ghi vào {args.baseline}")


if __name__ == "__main__":
    main()
