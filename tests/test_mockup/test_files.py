import csv
import gzip
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from openpyxl import load_workbook

from mockup.generate import write_mockup

SIZES = {"customers": 120, "battery_bills": 50, "tickets": 50, "devices": 10, "file_rows": 60, "log_lines": 300}


@pytest.fixture(scope="module")
def output(tmp_path_factory):
    root = tmp_path_factory.mktemp("mockup")
    write_mockup(root / "data", root / "labels", seed=11, sizes=SIZES)
    return root / "data" / "files", root / "labels"


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _csv_rows(path, delimiter, encoding):
    with path.open(encoding=encoding, newline="") as file:
        return list(csv.DictReader(file, delimiter=delimiter))


def test_csv_formats_read_back_with_their_delimiter_and_encoding(output):
    files, _ = output
    comma = _csv_rows(files / "csv/khach_hang_utf8.csv", ",", "utf-8")
    semicolon = _csv_rows(files / "csv/khach_hang_cham_phay.csv", ";", "utf-8-sig")
    tab = _csv_rows(files / "csv/thanh_toan_tab_utf16.csv", "\t", "utf-16")
    assert len(comma) == len(semicolon) == len(tab) == SIZES["file_rows"]
    assert comma == semicolon
    assert "chu_tk" in tab[0]


def test_xlsx_has_sheets_merged_title_and_date_cells(output):
    files, _ = output
    book = load_workbook(files / "excel/khach_hang.xlsx")
    assert book.sheetnames == ["KhachHang", "ThanhToan"]
    sheet = book["KhachHang"]
    assert len(sheet.merged_cells.ranges) == 1
    header = [cell.value for cell in sheet[2]]
    assert sheet.cell(row=3, column=header.index("ngay_sinh") + 1).is_date


def test_nested_json_has_deep_fields(output):
    files, _ = output
    documents = json.loads((files / "json/khach_hang.json").read_text(encoding="utf-8"))
    assert documents[0]["thong_tin"]["lien_he"]["email"]
    assert isinstance(documents[0]["hop_dong"], list)


def test_parquet_keeps_column_types(output):
    files, _ = output
    schema = pq.read_table(files / "parquet/thanh_toan.parquet").schema
    assert pa.types.is_decimal(schema.field("so_tien").type)
    assert pa.types.is_timestamp(schema.field("ngay_gd").type)
    assert pa.types.is_struct(schema.field("nguoi_tra").type)


def test_gz_holds_exactly_the_log_file(output):
    files, _ = output
    assert gzip.decompress((files / "log/app.log.gz").read_bytes()) == (files / "log/app.log").read_bytes()


def test_log_spans_point_at_values_on_their_line(output):
    files, labels_dir = output
    lines = (files / "log/app.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == SIZES["log_lines"]
    seen = set()
    for item in _jsonl(labels_dir / "file_spans.jsonl"):
        if item["file"] != "log/app.log":
            continue
        for span in item["labels"]:
            seen.add(span["type"])
            value = lines[item["line"] - 1][span["start"] : span["end"]]
            assert value and value == value.strip()
            if span["type"] == "IP_ADDRESS":
                assert value.count(".") == 3
    assert {"FULL_NAME", "PHONE", "EMAIL", "IP_ADDRESS", "SESSION_ID", "TOKEN", "PASSWORD", "GPS", "CCCD"} <= seen


def test_log_mixes_plain_and_json_lines(output):
    files, _ = output
    lines = (files / "log/app.log").read_text(encoding="utf-8").splitlines()
    json_lines = [line for line in lines if line.startswith("{")]
    assert json_lines and len(json_lines) < len(lines)
    assert all(json.loads(line)["event"] == "kyc" for line in json_lines)


def test_events_have_several_shapes_and_nested_json_strings(output):
    files, _ = output
    events = _jsonl(files / "log/events.jsonl")
    assert {event["event"] for event in events} == {"payment", "profile_update", "api_call"}
    payload = next(event["payload"] for event in events if event["event"] == "profile_update")
    assert set(json.loads(payload)) == {"phone", "cccd"}


def test_every_file_has_column_labels_with_group(output):
    files, labels_dir = output
    labels = _jsonl(labels_dir / "file_fields.jsonl")
    labelled = {label["file"] for label in labels}
    on_disk = {str(path.relative_to(files)) for path in files.rglob("*") if path.is_file()}
    assert on_disk - labelled == {"log/app.log", "log/app.log.gz", "log/secrets.log"}
    groups = {label["pii_type"]: label["group"] for label in labels}
    assert groups["BANK_ACCOUNT"] == "nhay_cam" and groups["CCCD"] == "co_ban"
    assert groups[None] is None


def test_gz_spans_match_log_spans(output):
    _, labels_dir = output
    items = _jsonl(labels_dir / "file_spans.jsonl")
    plain = [(item["line"], item["labels"]) for item in items if item["file"] == "log/app.log"]
    packed = [(item["line"], item["labels"]) for item in items if item["file"] == "log/app.log.gz"]
    assert plain == packed


def test_secret_log_spans_point_at_values_and_has_lines_without_secrets(output):
    files, labels_dir = output
    lines = (files / "log/secrets.log").read_text(encoding="utf-8").splitlines()
    items = [item for item in _jsonl(labels_dir / "file_spans.jsonl") if item["file"] == "log/secrets.log"]
    assert len(items) == len(lines) == SIZES["log_lines"]
    assert any(not item["labels"] for item in items)
    assert {span["type"] for item in items for span in item["labels"]} == {
        "TOKEN",
        "PASSWORD",
        "SESSION_ID",
        "IP_ADDRESS",
        "GPS",
    }
    for item in items:
        for span in item["labels"]:
            value = lines[item["line"] - 1][span["start"] : span["end"]]
            assert value and " " not in value
