"""Đo lõi trên mockup: python -m eval.run

Không cần MongoDB thật: nạp mockup vào mongomock rồi quét qua MongoConnector như luồng thật. Luôn tắt GLiNER để
số đo tái lập được. Báo cáo ghi rõ nguồn dữ liệu là mockup.
"""

import argparse
import gzip
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import mongomock
from bson import json_util

from eval.history import record, regressions, summarize_sections
from eval.leak import collect_values, load_labels, scan_output
from eval.metrics import score_fields, score_spans
from mockup.generate import DEFAULT_SEED
from piimask.connectors.mongo_connector import MongoConnector
from piimask.detection.ner_orchestrator import NERPipelines
from piimask.detection.rule_engine import RuleBasedScanner
from tool.export import export_database

_REPO = Path(__file__).resolve().parent.parent
_DATABASE = "mockup"
_BSON_OPTIONS = json_util.RELAXED_JSON_OPTIONS.with_options(tz_aware=True)
_APP_LOGS = ("log/app.log", "log/app.log.gz")
_SECRET_LOGS = ("log/secrets.log",)


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def load_collections(data_dir: Path) -> dict[str, list[dict]]:
    paths = sorted((data_dir / "mongo").glob("*.jsonl"))
    if not paths:
        sys.exit(f"Chưa có mockup ở {data_dir}. Chạy: python -m mockup.generate")
    collections = {}
    for path in paths:
        with path.open(encoding="utf-8") as file:
            collections[path.stem] = [json_util.loads(line, json_options=_BSON_OPTIONS) for line in file]
    return collections


def _connector(collections: dict[str, list[dict]]) -> MongoConnector:
    client = mongomock.MongoClient()
    for name, docs in collections.items():
        client[_DATABASE][name].insert_many(docs)
    return MongoConnector("mongodb://mockup", database_name=_DATABASE, client=client)


def scan_fields(collections: dict[str, list[dict]]) -> dict[str, str | None]:
    """Quét theo trường qua luồng thật. Trả 'collection.path' -> loại PII; None nếu lõi chưa kết luận."""
    scanner = RuleBasedScanner()
    connector = _connector(collections)
    predicted = {}
    for task in connector.to_scanner_contract():
        result = scanner.classify(task["column_profile"])
        key = f"{task['collection_name']}.{task['field_path']}"
        predicted[key] = result.inferred_pii_type if result else None
    return predicted


def evaluate_fields(collections: dict, labels_dir: Path) -> tuple[dict, float]:
    gold = [
        {**label, "key": f"{label['collection']}.{label['path']}"} for label in _read_jsonl(labels_dir / "fields.jsonl")
    ]
    started = time.perf_counter()
    predicted = scan_fields(collections)
    return score_fields(gold, predicted), time.perf_counter() - started


def scan_texts(pipeline: NERPipelines, texts: list[str]) -> list[list[tuple[int, int]]]:
    return [[(match.start, match.end) for match in pipeline.redact_with_matches(text)[1]] for text in texts]


def evaluate_tickets(collections: dict, labels_dir: Path, pipeline: NERPipelines) -> tuple[dict, float]:
    notes = {doc["TicketNo"]: doc["Note"] for doc in collections["tickets"]}
    spans = _read_jsonl(labels_dir / "text_spans.jsonl")
    started = time.perf_counter()
    predictions = scan_texts(pipeline, [notes[item["id"]] for item in spans])
    elapsed = time.perf_counter() - started
    return score_spans([(item["labels"], found) for item, found in zip(spans, predictions, strict=True)]), elapsed


def evaluate_logs(
    data_dir: Path, labels_dir: Path, pipeline: NERPipelines, files: tuple[str, ...] = _APP_LOGS
) -> tuple[dict, float, int]:
    """Quét file log theo từng dòng; dòng JSON cũng quét như văn bản vì chưa có bộ đọc log."""
    spans = [item for item in _read_jsonl(labels_dir / "file_spans.jsonl") if item.get("file") in files]
    contents = {}
    for file in sorted({item["file"] for item in spans}):
        path = data_dir / "files" / file
        raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        contents[file] = raw.decode("utf-8").splitlines()

    texts = [contents[item["file"]][item["line"] - 1] for item in spans]
    started = time.perf_counter()
    predictions = scan_texts(pipeline, texts)
    elapsed = time.perf_counter() - started
    result = score_spans([(item["labels"], found) for item, found in zip(spans, predictions, strict=True)])
    return result, elapsed, len(texts)


def evaluate_events(data_dir: Path, labels_dir: Path) -> dict:
    """Log object quét qua cùng luồng theo trường; chưa tách chuỗi JSON lồng."""
    events = _read_jsonl(data_dir / "files/log/events.jsonl")
    gold = [
        {**label, "key": f"app_events.{label['column']}"}
        for label in _read_jsonl(labels_dir / "file_fields.jsonl")
        if label["file"] == "log/events.jsonl"
    ]
    return score_fields(gold, scan_fields({"app_events": events}))


def evaluate_leak(collections: dict, labels_dir: Path) -> dict:
    """Xuất qua luồng thật rồi dò giá trị gốc của mọi trường có nhãn trong file đã che. Không tính văn bản tự do."""
    values: dict[str, str] = {}
    totals: Counter = Counter()
    for name, docs in collections.items():
        found, counts = collect_values(docs, load_labels(labels_dir / "fields.jsonl", name))
        values.update(found)
        totals.update(counts)

    with tempfile.TemporaryDirectory() as out_dir:
        export_database(
            _connector(collections), Path(out_dir), secret="eval", key_version="eval", join_keys=["IdNumber"]
        )
        left = scan_output(Path(out_dir), values)
    source = sum(totals.values())
    return {
        "source_occurrences": source,
        "raw_left_csv": sum(left["csv"].values()),
        "raw_left_xlsx": sum(left["xlsx"].values()),
        "raw_left_rate_csv": round(sum(left["csv"].values()) / source, 4),
        "by_type": dict(sorted(left["csv"].items())),
    }


def _commit() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_REPO, capture_output=True, text=True)
    return result.stdout.strip()


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def print_section(title: str, section: dict) -> None:
    print(f"\n{title}")
    print(
        f"  recall {_percent(section['recall'])} ({section['found']}/{section['total']}), "
        f"precision {_percent(section['precision'])}, báo nhầm {section['false_positives']}, "
        f"recall nhạy cảm {_percent(section['recall_nhay_cam'])}"
    )
    for pii_type, row in section["by_type"].items():
        print(f"  {pii_type:<14} {_percent(row['recall']):>7}  {row['found']}/{row['total']}")


def print_changes(report: dict, baseline: dict) -> None:
    print("\nSo với baseline")
    for name, section in report["sections"].items():
        old = baseline["sections"].get(name)
        if not old:
            print(f"  {name}: chưa có trong baseline")
            continue
        for metric in ("recall", "precision", "recall_nhay_cam"):
            before, after = old.get(metric), section.get(metric)
            if before is not None and after is not None and before != after:
                print(f"  {name}.{metric}: {_percent(before)} -> {_percent(after)}")


def build_report(data_dir: Path, labels_dir: Path) -> dict:
    collections = load_collections(data_dir)
    pipeline = NERPipelines(use_ml=False)

    fields, field_seconds = evaluate_fields(collections, labels_dir)
    tickets, ticket_seconds = evaluate_tickets(collections, labels_dir, pipeline)
    logs, log_seconds, log_count = evaluate_logs(data_dir, labels_dir, pipeline)
    secrets, _, _ = evaluate_logs(data_dir, labels_dir, pipeline, _SECRET_LOGS)
    events = evaluate_events(data_dir, labels_dir)
    leak = evaluate_leak(collections, labels_dir)
    documents = sum(len(docs) for docs in collections.values())
    return {
        "data_source": "mockup",
        "seed": DEFAULT_SEED,
        "commit": _commit(),
        "detector": "regex + quy tắc, GLiNER tắt",
        "sections": {
            "mongo_fields": fields,
            "mongo_free_text": tickets,
            "log_lines": logs,
            "log_secrets": secrets,
            "log_events": events,
        },
        "leak": leak,
        "not_measured": "CSV, Excel, JSON, Parquet: chưa có bộ đọc file",
        "performance": {
            "documents": documents,
            "field_scan_seconds": round(field_seconds, 2),
            "text_records_per_second": round(len(collections["tickets"]) / ticket_seconds),
            "log_lines_per_second": round(log_count / log_seconds),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=_REPO / "data/mockup")
    parser.add_argument("--labels-dir", type=Path, default=_REPO / "mockup/labels")
    parser.add_argument("--out", type=Path, default=_REPO / "eval/results/latest.json")
    parser.add_argument("--baseline", type=Path, default=_REPO / "eval/results/baseline.json")
    parser.add_argument("--record", metavar="MỐC", help="ghi kết quả vào history của baseline.json")
    args = parser.parse_args()

    report = build_report(args.data_dir, args.labels_dir)
    print(f"Nguồn: {report['data_source']}, bộ phát hiện: {report['detector']}, commit {report['commit']}")
    print_section("Theo trường (MongoDB)", report["sections"]["mongo_fields"])
    print_section("Văn bản tự do (tickets)", report["sections"]["mongo_free_text"])
    print_section("Dòng log (.log, .gz)", report["sections"]["log_lines"])
    print_section("Log bí mật (secrets.log)", report["sections"]["log_secrets"])
    print_section("Log object (events.jsonl)", report["sections"]["log_events"])
    print(f"\nRò rỉ trên bộ nhỏ: {report['leak']}")
    print(f"\nChưa đo: {report['not_measured']}")
    print(f"\nHiệu năng: {report['performance']}")

    if args.baseline.exists() and args.baseline.resolve() != args.out.resolve():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        print_changes(report, baseline)
        history = [item for item in baseline.get("history", []) if item["label"] != args.record]
        previous = history[-1]["small"]["sections"] if history else baseline["sections"]
        for line in regressions(report["sections"], previous):
            print(f"  TỤT so với mốc trước: {line}")

    if args.record:
        small = {
            "commit": report["commit"],
            "sections": summarize_sections(report["sections"]),
            "leak": report["leak"],
        }
        record(args.baseline, args.record, "small", small)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nĐã ghi {args.out}")


if __name__ == "__main__":
    main()
