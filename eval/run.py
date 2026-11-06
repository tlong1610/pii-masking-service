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
from eval.leak import collect_values, pii_labels, scan_output
from eval.metrics import score_catalog, score_fields, score_spans
from mockup.generate import DEFAULT_SEED
from mockup.heldout import STYLES, heldout_names, random_names, rename_document, rename_path, segments_of, style_of
from piimask.connectors.mongo_connector import MongoConnector
from piimask.detection.ner_orchestrator import NERPipelines
from piimask.transform.text_masker import mask_text
from tool.catalog import build_catalogs
from tool.export import build_plans, export_database

_REPO = Path(__file__).resolve().parent.parent
_DATABASE = "mockup"
_BSON_OPTIONS = json_util.RELAXED_JSON_OPTIONS.with_options(tz_aware=True)
_JOIN_KEYS = frozenset({"idnumber"})
_ENTERPRISE_FLAG = "EnterpriseCustomer"
_UNDECIDED_REASONS = ("chua_ket_luan", "ngoai_pham_vi_quet")
_APP_LOGS = ("log/app.log", "log/app.log.gz")
_SECRET_LOGS = ("log/secrets.log",)
_JSON_LOGS = ("log/json_numbers.log",)


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


def scan_fields(collections: dict[str, list[dict]], enterprise_flag: str | None = _ENTERPRISE_FLAG) -> dict:
    """Quyết định theo trường của luồng thật. Trả 'collection.path' -> loại PII; None nếu lõi chưa kết luận."""
    plans = build_plans(_connector(collections), _JOIN_KEYS, enterprise_flag=enterprise_flag)
    predicted = {}
    for collection, plan in plans.items():
        for path, decision in plan.items():
            pii_type = decision.pii_type
            if pii_type is None and decision.reason not in _UNDECIDED_REASONS:
                pii_type = "NOT_PERSONAL_DATA"
            predicted[f"{collection}.{path}"] = pii_type
    return predicted


def evaluate_fields(collections: dict, labels: list[dict], enterprise_flag: str | None) -> tuple[dict, float]:
    gold = [{**label, "key": f"{label['collection']}.{label['path']}"} for label in labels]
    started = time.perf_counter()
    predicted = scan_fields(collections, enterprise_flag)
    return score_fields(gold, predicted), time.perf_counter() - started


def evaluate_catalog(collections: dict, labels: list[dict], enterprise_flag: str | None) -> dict:
    """Danh mục sinh ra so với nhãn chuẩn, theo hành động của từng trường."""
    catalogs = build_catalogs(_connector(collections), _JOIN_KEYS, enterprise_flag=enterprise_flag)
    fields = {
        f"{catalog['collection']}.{field['path']}": field
        for catalog in catalogs.values()
        for field in catalog["fields"]
    }
    gold = [{**label, "key": f"{label['collection']}.{label['path']}"} for label in labels]
    return score_catalog(gold, fields)


def rename_set(collections: dict, labels: list[dict], make_names) -> tuple[dict, list[dict]]:
    """Đổi tên trường trong dữ liệu và nhãn. Trả thêm 'original' ở nhãn để báo theo kiểu đặt tên."""
    renamed, renamed_labels = {}, []
    for name, docs in collections.items():
        own = [label for label in labels if label["collection"] == name]
        names = make_names(name, segments_of(label["path"] for label in own))
        renamed[name] = [rename_document(doc, names) for doc in docs]
        for label in own:
            renamed_label = {**label, "path": rename_path(label["path"], names), "original": label["path"]}
            if "when" in label:
                renamed_label["when"] = {**label["when"], "field": names.get(label["when"]["field"])}
            renamed_labels.append(renamed_label)
    return renamed, renamed_labels


def flag_name(labels: list[dict]) -> str | None:
    return next((label["when"]["field"] for label in labels if "when" in label), None)


def recall_by_style(section: dict, labels: list[dict]) -> dict:
    missed = set(section["missed"])
    rows: dict[str, list[bool]] = {style: [] for style in STYLES}
    for label in labels:
        if label["pii_type"] is not None:
            leaf = label["original"].split(".")[-1].removesuffix("[]")
            rows[style_of(label["collection"], leaf)].append(f"{label['collection']}.{label['path']}" not in missed)
    return {style: {"found": sum(hits), "total": len(hits)} for style, hits in rows.items()}


def scan_texts(pipeline: NERPipelines, texts: list[str]) -> list[list[tuple[int, int]]]:
    return [[(entity.start, entity.end) for entity in mask_text(text, pipeline=pipeline).entities] for text in texts]


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


def evaluate_json_validity(data_dir: Path, pipeline: NERPipelines) -> dict:
    """Dòng JSON sau khi che phải còn hợp lệ với cùng bộ khóa."""
    lines = (data_dir / "files" / _JSON_LOGS[0]).read_text(encoding="utf-8").splitlines()
    valid = 0
    for line in lines:
        try:
            valid += set(json.loads(mask_text(line, pipeline=pipeline).text)) == set(json.loads(line))
        except ValueError:
            pass
    return {"lines": len(lines), "valid_after_mask": valid}


def evaluate_events(data_dir: Path, labels_dir: Path) -> dict:
    """Log object quét qua cùng luồng theo trường."""
    events = _read_jsonl(data_dir / "files/log/events.jsonl")
    gold = [
        {**label, "key": f"app_events.{label['column']}"}
        for label in _read_jsonl(labels_dir / "file_fields.jsonl")
        if label["file"] == "log/events.jsonl"
    ]
    return score_fields(gold, scan_fields({"app_events": events}))


def evaluate_leak(collections: dict, labels: list[dict], enterprise_flag: str | None) -> dict:
    """Xuất qua luồng thật rồi dò giá trị gốc của mọi trường có nhãn trong file đã che. Không tính văn bản tự do."""
    values: dict[str, str] = {}
    totals: Counter = Counter()
    allowed: set[str] = set()
    for name, docs in collections.items():
        found, counts, exempt = collect_values(docs, pii_labels(labels, name))
        values.update(found)
        totals.update(counts)
        allowed |= exempt
    for value in allowed:
        values.pop(value, None)

    with tempfile.TemporaryDirectory() as out_dir:
        export_database(
            _connector(collections),
            Path(out_dir),
            secret="eval",
            key_version="eval",
            join_keys=["IdNumber"],
            enterprise_flag=enterprise_flag,
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


def build_report(data_dir: Path, labels_dir: Path, rename_seed: int = 1) -> dict:
    collections = load_collections(data_dir)
    labels = _read_jsonl(labels_dir / "fields.jsonl")
    labels = [label for label in labels if label["collection"] in collections]
    pipeline = NERPipelines(use_ml=False)

    fields, field_seconds = evaluate_fields(collections, labels, _ENTERPRISE_FLAG)
    heldout_data, heldout_labels = rename_set(collections, labels, heldout_names)
    # Tên cờ doanh nghiệp là cấu hình của từng nguồn, nên hai bộ đổi tên dùng tên mới của nó.
    heldout_flag = flag_name(heldout_labels)
    heldout, _ = evaluate_fields(heldout_data, heldout_labels, heldout_flag)
    heldout["by_style"] = recall_by_style(heldout, heldout_labels)
    random_data, random_labels = rename_set(
        collections, labels, lambda name, segments: random_names(name, segments, rename_seed)
    )
    random_flag = flag_name(random_labels)
    randomized, _ = evaluate_fields(random_data, random_labels, random_flag)
    tickets, ticket_seconds = evaluate_tickets(collections, labels_dir, pipeline)
    logs, log_seconds, log_count = evaluate_logs(data_dir, labels_dir, pipeline)
    secrets, _, _ = evaluate_logs(data_dir, labels_dir, pipeline, _SECRET_LOGS)
    json_logs, _, _ = evaluate_logs(data_dir, labels_dir, pipeline, _JSON_LOGS)
    json_logs["json_validity"] = evaluate_json_validity(data_dir, pipeline)
    events = evaluate_events(data_dir, labels_dir)
    leak = {
        "goc": evaluate_leak(collections, labels, _ENTERPRISE_FLAG),
        "heldout": evaluate_leak(heldout_data, heldout_labels, heldout_flag),
        "ngau_nhien": evaluate_leak(random_data, random_labels, random_flag),
    }
    catalog = {
        "goc": evaluate_catalog(collections, labels, _ENTERPRISE_FLAG),
        "heldout": evaluate_catalog(heldout_data, heldout_labels, heldout_flag),
        "ngau_nhien": evaluate_catalog(random_data, random_labels, random_flag),
    }
    documents = sum(len(docs) for docs in collections.values())
    return {
        "data_source": "mockup",
        "seed": DEFAULT_SEED,
        "commit": _commit(),
        "detector": "regex + quy tắc, GLiNER tắt",
        "sections": {
            "mongo_fields": fields,
            "mongo_fields_heldout": heldout,
            "mongo_fields_random": randomized,
            "mongo_free_text": tickets,
            "log_lines": logs,
            "log_secrets": secrets,
            "log_json": json_logs,
            "log_events": events,
        },
        "leak": leak,
        "catalog": catalog,
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
    parser.add_argument("--rename-seed", type=int, default=1, help="seed của chế độ đổi tên ngẫu nhiên")
    args = parser.parse_args()

    report = build_report(args.data_dir, args.labels_dir, args.rename_seed)
    print(f"Nguồn: {report['data_source']}, bộ phát hiện: {report['detector']}, commit {report['commit']}")
    print_section("Theo trường (MongoDB)", report["sections"]["mongo_fields"])
    print_section("Theo trường, bộ held-out", report["sections"]["mongo_fields_heldout"])
    print(f"  theo kiểu tên: {report['sections']['mongo_fields_heldout']['by_style']}")
    print_section("Theo trường, đổi tên ngẫu nhiên", report["sections"]["mongo_fields_random"])
    print_section("Văn bản tự do (tickets)", report["sections"]["mongo_free_text"])
    print_section("Dòng log (.log, .gz)", report["sections"]["log_lines"])
    print_section("Log bí mật (secrets.log)", report["sections"]["log_secrets"])
    print_section("Log JSON có PII dạng số (json_numbers.log)", report["sections"]["log_json"])
    print(f"  {report['sections']['log_json']['json_validity']}")
    print_section("Log object (events.jsonl)", report["sections"]["log_events"])
    print(f"\nRò rỉ trên bộ nhỏ: {report['leak']}")
    print(f"\nDanh mục: {report['catalog']}")
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
            "catalog": report["catalog"],
        }
        record(args.baseline, args.record, "small", small)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nĐã ghi {args.out}")


if __name__ == "__main__":
    main()
