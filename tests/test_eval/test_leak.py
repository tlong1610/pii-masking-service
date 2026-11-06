import csv
import json

import mongomock
import pytest
from openpyxl import Workbook

from eval.leak import build_matcher, collect_values, count_in_lines, load_labels, scan_output
from mockup.load_perf import PERF_COLLECTION, RareField, load_perf, rare_values
from piimask.connectors.mongo_connector import MongoConnector
from tool.export import export_database

LABELS = {
    "Phone": {"pii_type": "PHONE"},
    "Tax": {"pii_type": "TAX_CODE", "when": {"field": "Enterprise", "equals": False}},
    "Items[].Serial": {"pii_type": "VIN"},
}


def test_collect_values_applies_conditions_and_reads_arrays():
    documents = [
        {"Phone": "0912345678", "Tax": "8000000001", "Enterprise": False, "Items": [{"Serial": "S1"}]},
        {"Phone": "", "Tax": "0100000001", "Enterprise": True},
        {"Phone": None},
    ]
    values, totals, allowed = collect_values(documents, LABELS)
    assert values == {"0912345678": "PHONE", "8000000001": "TAX_CODE", "S1": "VIN"}
    assert totals == {"PHONE": 1, "TAX_CODE": 1, "VIN": 1}
    assert allowed == {"0100000001"}


def test_load_labels_skips_other_collections_and_free_text(tmp_path):
    path = tmp_path / "fields.jsonl"
    rows = [
        {"collection": "a", "path": "x", "pii_type": "PHONE"},
        {"collection": "a", "path": "y", "pii_type": None},
        {"collection": "a", "path": "z", "pii_type": "FREE_TEXT"},
        {"collection": "b", "path": "x", "pii_type": "EMAIL"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert set(load_labels(path, "a")) == {"x"}


def test_matcher_counts_whole_values_only():
    matcher = build_matcher({"0912345678": "PHONE", "kh@example.com": "EMAIL"})
    lines = ["a,0912345678,b", "kh@example.com 0912345678", "ab0912345678cd", "091***678"]
    assert count_in_lines(matcher, lines) == {"PHONE": 2, "EMAIL": 1}


def test_scan_output_reads_csv_and_xlsx_and_ignores_report(tmp_path):
    with (tmp_path / "t.csv").open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file).writerows([["a"], ["0912345678"], ["***"]])
    book = Workbook()
    book.active.append(["a"])
    book.active.append(["gọi 0912345678 nhé"])
    book.active.append(["0912345678"])
    book.save(tmp_path / "t.xlsx")
    (tmp_path / "report.json").write_text("0912345678", encoding="utf-8")

    found = scan_output(tmp_path, {"0912345678": "PHONE"})
    assert found["csv"] == {"PHONE": 1}
    assert found["xlsx"] == {"PHONE": 2}


def _export_with(rare_field, count=150):
    """Nạp bill có trường hiếm, xuất ra thư mục tạm; trả báo cáo collection."""
    client = mongomock.MongoClient()
    load_perf(client, "p", count=count, rare_fields=[rare_field])
    return MongoConnector("mongodb://mockup", database_name="p", client=client)


def _late(path):
    return RareField(path, "PHONE", "ca thử", 120, 10, lambda v: v.phone())


@pytest.fixture
def raw_left(tmp_path):
    def run(field):
        connector = _export_with(field)
        report = export_database(connector, tmp_path, secret="s", key_version="v1", formats=["csv"])
        fields = {item["path"]: item for item in report["collections"][PERF_COLLECTION]["fields"]}
        values = {value: "PHONE" for value in rare_values([field], 150)[field.path].values()}
        return fields[field.path], scan_output(tmp_path, values)["csv"]["PHONE"]

    return run


def test_field_first_seen_in_late_documents_is_detected(raw_left):
    decision, left = raw_left(_late("SoDienThoaiPhu"))
    assert decision["pii_type"] == "PHONE" and decision["reason"] == "phat_hien"
    assert left == 0


def test_phone_typed_into_a_kept_field_is_caught_by_last_guard(raw_left):
    decision, left = raw_left(_late("PaidAt.StoreName"))
    assert decision["action"] == "KEEP"
    assert decision["guard_hits"] == 3
    assert left == 0
