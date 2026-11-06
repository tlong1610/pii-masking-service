"""Đo tốc độ và rò rỉ trên collection lớn: python -m eval.perf --update-baseline

Cần MongoDB đang chạy và đã nạp mockup.load_perf. Đọc bằng MONGO_URI (tài khoản chỉ đọc). Số đo phụ thuộc máy chạy,
báo cáo ghi kèm số CPU. File xuất ghi vào thư mục tạm rồi xóa. Có --api-url thì đo thêm độ trễ API.

Sau khi xuất, dò lại toàn bộ file đã che để đếm giá trị PII gốc còn sót, và báo từng trường hiếm đã gài có được bộ quét
phát hiện, có bị lộ không.
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

from eval.leak import collect_values, load_labels, scan_output
from eval.run import _commit
from mockup.load_perf import PERF_COLLECTION, RARE_FIELDS, perf_database, rare_values
from piimask.config import get_settings
from piimask.connectors.mongo_connector import MongoConnector
from tool.export import export_database

_REPO = Path(__file__).resolve().parent.parent
_LABELS = _REPO / "mockup/labels/fields.jsonl"
_DEV_SECRET = "chi-dung-de-do-toc-do"
# Số document đầu mà MongoConnector xem khi quét theo trường.
_SCANNED_DOCUMENTS = 100
_API_SAMPLE = (
    "Khách gọi 0912345678, email demo.kh@example.com, CCCD 001099012345, hẹn gặp tại trạm sạc số 12 lúc 9 giờ sáng. "
    "Mã vận đơn và số tiền giữ nguyên để đối soát."
)


def measure_export(connector: MongoConnector, formats: list[str], out_dir: Path) -> tuple[dict, dict]:
    """Trả số đo tốc độ và báo cáo của collection vừa xuất."""
    started = time.perf_counter()
    report = export_database(
        connector,
        out_dir,
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
    }, result


def _count_documents(connector: MongoConnector) -> int:
    return sum(1 for _ in connector.iter_documents(PERF_COLLECTION))


def measure_leak(connector: MongoConnector, out_dir: Path, fields: list[dict]) -> dict:
    """Dò giá trị gốc của trường có nhãn và trường hiếm đã gài trong mọi file ở out_dir."""
    documents = connector.iter_documents(PERF_COLLECTION)
    values, totals = collect_values(documents, load_labels(_LABELS, PERF_COLLECTION))
    labelled_values = len(values)

    planted = rare_values(RARE_FIELDS, _count_documents(connector))
    for field in RARE_FIELDS:
        for value in planted[field.path].values():
            values[value] = f"rare:{field.path}"

    started = time.perf_counter()
    found = scan_output(out_dir, values)
    seconds = time.perf_counter() - started

    decisions = {item["path"]: item for item in fields}
    rare = []
    for field in RARE_FIELDS:
        decision = decisions[field.path]
        key = f"rare:{field.path}"
        rare.append(
            {
                "path": field.path,
                "pii_type": field.pii_type,
                "case": field.case,
                "documents": len(planted[field.path]),
                "in_scanned_documents": field.start < _SCANNED_DOCUMENTS,
                "detected_type": decision["pii_type"],
                "action": decision["action"],
                "reason": decision["reason"],
                "raw_left_csv": found["csv"][key],
                "raw_left_xlsx": found["xlsx"][key],
            }
        )

    by_type = {
        pii_type: {"source": total, "raw_left_csv": found["csv"][pii_type], "raw_left_xlsx": found["xlsx"][pii_type]}
        for pii_type, total in sorted(totals.items())
    }
    source = sum(totals.values())
    left_csv = sum(row["raw_left_csv"] for row in by_type.values())
    left_xlsx = sum(row["raw_left_xlsx"] for row in by_type.values())
    return {
        "leak": {
            "unique_values_checked": labelled_values,
            "source_occurrences": source,
            "raw_left_csv": left_csv,
            "raw_left_xlsx": left_xlsx,
            "raw_left_rate_csv": round(left_csv / source, 4),
            "raw_left_rate_xlsx": round(left_xlsx / source, 4),
            "by_type": by_type,
            "scan_seconds": round(seconds, 2),
            "note": "Không tính phần thân văn bản tự do; trường hiếm đã gài báo riêng ở rare_fields.",
        },
        "rare_fields": rare,
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
        with tempfile.TemporaryDirectory() as csv_dir, tempfile.TemporaryDirectory() as both_dir:
            csv_speed, _ = measure_export(connector, ["csv"], Path(csv_dir))
            both_speed, result = measure_export(connector, ["csv", "xlsx"], Path(both_dir))
            # Bộ nhớ đỉnh chỉ tính lượt quét và xuất, lượt dò rò rỉ cố ý nạp giá trị gốc vào bộ nhớ.
            peak_memory = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
            leak = measure_leak(connector, Path(both_dir), result["fields"])
    finally:
        client.close()

    report = {
        "data_source": "mockup, chỉ đo tốc độ",
        "commit": _commit(),
        "cpu_count": os.cpu_count(),
        "detector": "regex + quy tắc, GLiNER tắt",
        "csv": csv_speed,
        "csv_xlsx": both_speed,
        "peak_memory_mb": peak_memory,
    }
    if args.api_url:
        report["api"] = measure_api(args.api_url)

    print(json.dumps({**report, **leak}, ensure_ascii=False, indent=2))
    if args.update_baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        baseline["performance_large"] = report
        baseline["leak_large"] = leak["leak"]
        baseline["rare_fields_large"] = leak["rare_fields"]
        args.baseline.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Đã ghi vào {args.baseline}")


if __name__ == "__main__":
    main()
