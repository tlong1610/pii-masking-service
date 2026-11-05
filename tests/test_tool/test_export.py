import csv
import json
from datetime import UTC, datetime

import mongomock
import pytest
from bson import Decimal128, ObjectId
from openpyxl import load_workbook

from piimask.connectors.mongo_connector import MongoConnector
from piimask.transform.hmac_hasher import hash_value
from tool import export as export_module
from tool.export import export_database, table_file_name
from tool.writers import WRITERS, XlsxWriter, to_cell

SECRET, VERSION = "test-secret", "v1"
PHONE, EMAIL, CCCD, SERIAL = "0912345678", "kh.demo@example.com", "001099012345", "DEMOSERIAL0001"


def _doc(index, **extra):
    return {
        "_id": ObjectId(f"{index:024x}"),
        "FullName": f"Khách Hàng {index}",
        "PhoneNumber": PHONE,
        "Email": EMAIL,
        "IdNumber": CCCD,
        "Amount": Decimal128("1500.50"),
        "CreatedDate": datetime(2026, 1, 2, 3, 4, 5),
        "Batteries": [{"Serial": SERIAL, "Stock": "A"}, {"Serial": SERIAL, "Stock": "B"}],
        **extra,
    }


def _export(tmp_path, docs, **options):
    client = mongomock.MongoClient()
    client["src"]["contracts"].insert_many(docs)
    connector = MongoConnector("mongodb://mockup", database_name="src", client=client)
    return export_database(connector, tmp_path, secret=SECRET, key_version=VERSION, join_keys=["IdNumber"], **options)


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_exports_csv_and_xlsx_with_same_row_count(tmp_path):
    report = _export(tmp_path, [_doc(1), _doc(2)])
    result = report["collections"]["contracts"]
    assert result["documents"] == 2
    assert result["rows"] == {"contracts": 2, "Batteries": 4}
    assert sorted(result["files"]) == [
        "contracts.csv",
        "contracts.xlsx",
        "contracts__Batteries.csv",
        "contracts__Batteries.xlsx",
    ]
    assert load_workbook(tmp_path / "contracts.xlsx")["data"].max_row == 3


def test_detected_fields_follow_policy(tmp_path):
    _export(tmp_path, [_doc(1)])
    (row,) = _rows(tmp_path / "contracts.csv")
    assert row["FullName"] == "***"
    assert row["PhoneNumber"] == "091***678"
    assert row["Email"] == hash_value(EMAIL, secret=SECRET, key_version=VERSION)
    assert row["IdNumber"] == hash_value(CCCD, secret=SECRET, key_version=VERSION)


def test_raw_values_never_reach_any_file(tmp_path):
    _export(tmp_path, [_doc(1), _doc(2)])
    for path in tmp_path.iterdir():
        content = path.read_bytes() if path.suffix != ".xlsx" else _xlsx_text(path).encode()
        for value in (PHONE, EMAIL, CCCD, SERIAL):
            assert value.encode() not in content, path.name


def _xlsx_text(path):
    sheet = load_workbook(path)["data"]
    return " ".join(str(cell) for row in sheet.iter_rows(values_only=True) for cell in row)


def test_child_rows_link_to_parent_through_hmac(tmp_path):
    _export(tmp_path, [_doc(1), _doc(2)])
    parents = {row["_id"] for row in _rows(tmp_path / "contracts.csv")}
    children = _rows(tmp_path / "contracts__Batteries.csv")
    assert {row["_parent_key"] for row in children} == parents
    assert str(ObjectId(f"{1:024x}")) not in parents
    assert [row["_index"] for row in children] == ["0", "1", "0", "1"]
    assert len({row["_row_key"] for row in children}) == 4


def test_nested_array_child_links_to_child_row(tmp_path):
    _export(tmp_path, [_doc(1, Packs=[{"Cells": [{"Id": 1}]}])])
    packs = _rows(tmp_path / "contracts__Packs.csv")
    cells = _rows(tmp_path / "contracts__Packs__Cells.csv")
    assert cells[0]["_parent_key"] == packs[0]["_row_key"]


def test_field_outside_scanned_documents_is_masked(tmp_path):
    # Quét theo trường chỉ xem 100 document đầu: trường xuất hiện sau đó chưa có quyết định.
    docs = [_doc(index) for index in range(1, 121)]
    docs[-1]["GhiChuMoi"] = f"gọi {PHONE}"
    report = _export(tmp_path, docs)
    row = _rows(tmp_path / "contracts.csv")[-1]
    assert row["GhiChuMoi"] == "***"
    decision = next(item for item in report["collections"]["contracts"]["fields"] if item["path"] == "GhiChuMoi")
    assert decision["reason"] == "ngoai_pham_vi_quet"


def test_field_nested_deeper_than_scan_is_masked(tmp_path):
    _export(tmp_path, [_doc(1, a={"b": {"c": {"d": PHONE}}})])
    (row,) = _rows(tmp_path / "contracts.csv")
    assert row["a.b.c.d"] == "***"


def test_array_fields_are_masked_until_scanner_covers_arrays(tmp_path):
    report = _export(tmp_path, [_doc(1)])
    assert {row["Stock"] for row in _rows(tmp_path / "contracts__Batteries.csv")} == {"***"}
    fields = {item["path"]: item for item in report["collections"]["contracts"]["fields"]}
    assert fields["Batteries[].Serial"]["reason"] == "ngoai_pham_vi_quet"


def test_report_has_decisions_but_no_values(tmp_path):
    _export(tmp_path, [_doc(1)])
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["hmac_key_version"] == VERSION
    fields = {item["path"]: item for item in report["collections"]["contracts"]["fields"]}
    assert fields["PhoneNumber"]["pii_type"] == "PHONE"
    assert SECRET not in json.dumps(report)


def test_collection_filter(tmp_path):
    report = _export(tmp_path, [_doc(1)], collections=[])
    assert report["collections"] == {}
    assert not list(tmp_path.glob("*.csv"))


def test_failed_export_leaves_no_partial_file(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("che lỗi")

    monkeypatch.setattr(export_module, "apply_action", boom)
    with pytest.raises(RuntimeError):
        _export(tmp_path, [_doc(1)])
    assert [path for path in tmp_path.iterdir() if path.name != "report.json"] == []


def test_file_name_cannot_leave_output_directory():
    assert "/" not in table_file_name("a/../../b", "c/d")
    assert table_file_name("x", "a[].b") == "x__a__b"


def test_cell_conversion():
    assert str(to_cell(Decimal128("12.50"))) == "12.50"
    assert to_cell(Decimal128("NaN")) == "NaN"
    assert to_cell(float("inf")) == "inf"
    assert to_cell(ObjectId("0" * 24)) == "0" * 24
    assert to_cell(datetime(2026, 1, 1, 7, tzinfo=UTC)) == datetime(2026, 1, 1, 7)
    assert to_cell(None) is None and to_cell(True) is True


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_writer_handles_every_cell_type(tmp_path, name):
    writer = WRITERS[name](tmp_path / f"t{WRITERS[name].suffix}", ["a", "b", "c", "d"])
    writer.write([Decimal128("1.5"), datetime(2026, 1, 1), None, "bình thường"])
    writer.commit()
    assert writer.path.exists() and not writer.part.exists()


def test_xlsx_keeps_formula_like_text_as_text_and_drops_control_characters(tmp_path):
    writer = XlsxWriter(tmp_path / "t.xlsx", ["a", "b"])
    writer.write(["=1+1", "có\x01ký tự"])
    writer.commit()
    sheet = load_workbook(tmp_path / "t.xlsx")["data"]
    assert sheet["A2"].value == "=1+1" and sheet["A2"].data_type == "s"
    assert sheet["B2"].value == "cóký tự"


def test_xlsx_refuses_more_rows_than_the_format_holds(tmp_path, monkeypatch):
    monkeypatch.setattr("tool.writers.XLSX_MAX_ROWS", 2)
    writer = XlsxWriter(tmp_path / "t.xlsx", ["a"])
    writer.write(["x"])
    with pytest.raises(ValueError, match="dòng"):
        writer.write(["y"])
    writer.abort()
    assert not writer.part.exists()
