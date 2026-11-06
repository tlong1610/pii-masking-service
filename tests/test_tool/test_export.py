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


def test_field_only_in_late_document_is_scanned(tmp_path):
    docs = [_doc(index) for index in range(1, 121)]
    docs[-1]["GhiChuMoi"] = f"gọi {PHONE} nhé"
    report = _export(tmp_path, docs)
    assert _rows(tmp_path / "contracts.csv")[-1]["GhiChuMoi"] == "gọi [PHONE] nhé"
    decision = next(item for item in report["collections"]["contracts"]["fields"] if item["path"] == "GhiChuMoi")
    assert decision["pii_type"] == "FREE_TEXT_PII"


def test_field_nested_deeper_than_two_levels_is_scanned(tmp_path):
    _export(tmp_path, [_doc(1, a={"b": {"c": {"d": PHONE}}})])
    (row,) = _rows(tmp_path / "contracts.csv")
    assert row["a.b.c.d"] == "091***678"


def test_field_in_array_is_scanned(tmp_path):
    report = _export(tmp_path, [_doc(1, Contacts=[{"Email": EMAIL}])])
    assert _rows(tmp_path / "contracts__Contacts.csv")[0]["Email"] == hash_value(
        EMAIL, secret=SECRET, key_version=VERSION
    )
    fields = {item["path"]: item for item in report["collections"]["contracts"]["fields"]}
    assert fields["Contacts[].Email"]["pii_type"] == "EMAIL"


def test_json_string_field_stays_valid_json(tmp_path):
    payload = json.dumps({"phone": PHONE, "n": 123456789012})
    _export(tmp_path, [_doc(1, payload=payload)])
    (row,) = _rows(tmp_path / "contracts.csv")
    assert json.loads(row["payload"]) == {"phone": "[PHONE]", "n": "[CCCD]"}


def test_undecided_field_is_masked_whole(tmp_path):
    report = _export(tmp_path, [_doc(1, f17="abc")])
    (row,) = _rows(tmp_path / "contracts.csv")
    assert row["f17"] == "***"
    fields = {item["path"]: item for item in report["collections"]["contracts"]["fields"]}
    assert fields["f17"]["reason"] == "chua_ket_luan"


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


def test_last_guard_masks_pii_in_a_kept_field_and_reports_count(tmp_path):
    docs = [_doc(index, StoreName=f"Showroom {index}") for index in range(1, 40)]
    docs[-1]["StoreName"] = f"gọi {PHONE}"
    report = _export(tmp_path, docs)
    rows = _rows(tmp_path / "contracts.csv")
    assert rows[0]["StoreName"] == "Showroom 1"
    assert rows[-1]["StoreName"] == "gọi [PHONE]"
    fields = {item["path"]: item for item in report["collections"]["contracts"]["fields"]}
    assert fields["StoreName"]["action"] == "KEEP" and fields["StoreName"]["guard_hits"] == 1


def test_waybill_format_is_routine_in_its_field_but_phone_there_is_still_caught(tmp_path):
    docs = [_doc(index, TrackingCode=f"4006911725{index:02d}") for index in range(1, 40)]
    docs[-1]["TrackingCode"] = f"gọi {PHONE}"
    report = _export(tmp_path, docs)
    rows = _rows(tmp_path / "contracts.csv")
    assert rows[0]["TrackingCode"] == "400691172501"
    assert rows[-1]["TrackingCode"] == "gọi [PHONE]"
    fields = {item["path"]: item for item in report["collections"]["contracts"]["fields"]}
    assert list(fields["TrackingCode"]["guard_exempt"]) == ["CCCD"]


def _customer(index, enterprise):
    document = {
        "_id": ObjectId(f"{index:024x}"),
        "Phone": PHONE,
        "CustomerId": f"20080000{index:04d}",
        "TaxRegistrationNumber": f"010{index:07d}",
        "Vehicle": {"VehicleId": "1HGCM82633A004352"},
        "Items": [{"Serial": f"SN{index}"}],
    }
    if enterprise is not None:
        document["EnterpriseCustomer"] = enterprise
    return document


def _export_customers(tmp_path, documents):
    client = mongomock.MongoClient()
    client["src"]["kh"].insert_many(documents)
    connector = MongoConnector("mongodb://mockup", database_name="src", client=client)
    return export_database(
        connector, tmp_path, secret=SECRET, key_version=VERSION, formats=["csv"], enterprise_flag="EnterpriseCustomer"
    )


def test_enterprise_row_keeps_conditional_fields_and_individual_row_hides_them(tmp_path):
    _export_customers(tmp_path, [_customer(1, True), _customer(2, False)])
    enterprise, individual = _rows(tmp_path / "kh.csv")
    assert enterprise["CustomerId"] == "200800000001"
    assert enterprise["TaxRegistrationNumber"] == "0100000001"
    assert enterprise["Vehicle.VehicleId"] == "1HGCM82633A004352"
    assert enterprise["Phone"] == "091***678"
    assert individual["CustomerId"] == hash_value("200800000002", secret=SECRET, key_version=VERSION)
    assert individual["TaxRegistrationNumber"] == "***"
    assert individual["Vehicle.VehicleId"] == hash_value("1HGCM82633A004352", secret=SECRET, key_version=VERSION)


def test_enterprise_flag_reaches_rows_of_child_tables(tmp_path):
    _export_customers(tmp_path, [_customer(1, True), _customer(2, False)])
    enterprise, individual = _rows(tmp_path / "kh__Items.csv")
    assert enterprise["Serial"] == "SN1"
    assert individual["Serial"] == hash_value("SN2", secret=SECRET, key_version=VERSION)


@pytest.mark.parametrize("flag", [None, "True", 1])
def test_row_without_a_real_true_flag_counts_as_individual(tmp_path, flag):
    documents = [_customer(1, True), _customer(2, False), {**_customer(3, False), "EnterpriseCustomer": flag}]
    _export_customers(tmp_path, documents)
    assert _rows(tmp_path / "kh.csv")[2]["CustomerId"] == hash_value("200800000003", secret=SECRET, key_version=VERSION)


def test_collection_without_flag_always_masks(tmp_path):
    _export_customers(tmp_path, [_customer(1, None)])
    (row,) = _rows(tmp_path / "kh.csv")
    assert row["CustomerId"] == hash_value("200800000001", secret=SECRET, key_version=VERSION)
