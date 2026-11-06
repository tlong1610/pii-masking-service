"""Luồng end-to-end trên MongoDB trong Docker, đọc bằng user chỉ đọc."""

import csv
import json
from pathlib import Path

import pytest
from pymongo.errors import OperationFailure

from piimask.connectors.mongo_connector import MongoConnector
from piimask.transform.flatten import field_path, split_document
from tool.export import export_database, table_file_name

LABELS = Path(__file__).resolve().parents[2] / "mockup/labels/fields.jsonl"

# Trường có nhãn PII nhưng bộ phát hiện kết luận KEEP, sẽ sửa ở bước mã khách và số khung. Danh sách này phải khớp
# đúng: trường mới lọt ra làm test đỏ, sửa xong detector thì xóa khỏi đây. Test dò giá trị trong cả file nên
# BatterySerial có ở đây dù cột của nó đã bị che: giá trị trùng với VehicleId, cột đó đang giữ nguyên.
KNOWN_DETECTOR_GAPS = {
    "battery_bills.BatterySerial",
    "battery_bills.CustomerId",
    "battery_bills.SapCustomerId",
    "battery_bills.VehicleId",
    "battery_contracts.CustomerId",
    "battery_contracts.SapCustomerId",
    "battery_contracts.VehicleId",
    "customers.CustomerId",
    "customers.SapCustomerId",
    "tickets.CustomerId",
}


@pytest.fixture(scope="module")
def exported(readonly_client, tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("export")
    connector = MongoConnector("mongodb://mockup", database_name="mockup", client=readonly_client)
    report = export_database(connector, out_dir, secret="it-secret", key_version="v1", join_keys=["IdNumber"])
    return out_dir, report


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def test_source_account_cannot_write(readonly_client):
    collection = readonly_client["mockup"]["customers"]
    with pytest.raises(OperationFailure):
        collection.insert_one({"a": 1})
    with pytest.raises(OperationFailure):
        collection.update_many({}, {"$set": {"a": 1}})
    with pytest.raises(OperationFailure):
        collection.drop()


def test_every_document_is_exported(readonly_client, exported):
    out_dir, report = exported
    for name, result in report["collections"].items():
        assert result["documents"] == readonly_client["mockup"][name].count_documents({})
        assert len(_rows(out_dir / f"{name}.csv")) == result["documents"]
        assert all((out_dir / file).exists() for file in result["files"])


def test_contract_batteries_link_back_to_contracts(exported):
    out_dir, _ = exported
    parents = {row["_id"] for row in _rows(out_dir / "battery_contracts.csv")}
    children = _rows(out_dir / "battery_contracts__Batteries.csv")
    assert children and {row["_parent_key"] for row in children} <= parents


def test_join_key_still_joins_across_collections(exported):
    out_dir, _ = exported
    customers = {row["IdNumber"] for row in _rows(out_dir / "customers.csv")}
    contracts = {row["IdNumber"] for row in _rows(out_dir / "battery_contracts.csv")}
    bills = {row["IDNumber"] for row in _rows(out_dir / "battery_bills.csv")}
    assert contracts <= customers and bills <= customers


def _labelled_values(readonly_client):
    """(collection, bảng, đường dẫn) -> giá trị gốc của mọi trường có nhãn PII, đã xét điều kiện khách cá nhân."""
    with LABELS.open(encoding="utf-8") as file:
        labels = [json.loads(line) for line in file]
    gold = {(item["collection"], item["path"]): item for item in labels if item["pii_type"] not in (None, "FREE_TEXT")}
    values: dict[tuple, set] = {}
    for collection in {name for name, _ in gold}:
        for document in readonly_client["mockup"][collection].find({}):
            for row in split_document(document, "k"):
                for column, value in row.fields.items():
                    label = gold.get((collection, field_path(row.table, column)))
                    if label is None or value in (None, ""):
                        continue
                    condition = label.get("when")
                    if condition and document.get(condition["field"]) != condition["equals"]:
                        continue
                    key = (collection, row.table, field_path(row.table, column))
                    values.setdefault(key, set()).add(str(value))
    return values


def test_only_known_detector_gaps_leak_raw_values(readonly_client, exported):
    out_dir, _ = exported
    leaked = set()
    for (collection, table, path), values in _labelled_values(readonly_client).items():
        file = out_dir / f"{table_file_name(collection, table)}.csv"
        content = file.read_text(encoding="utf-8-sig")
        if any(value in content for value in values):
            leaked.add(f"{collection}.{path}")
    assert leaked == KNOWN_DETECTOR_GAPS
