import json
import re
from collections import Counter

import pytest
from bson import json_util
from bson.decimal128 import Decimal128
from bson.objectid import ObjectId

from mockup.generate import build_collections, write_mockup
from mockup.labels import PII_FIELDS, field_labels, field_paths

SIZES = {"customers": 120, "battery_bills": 200, "tickets": 400, "devices": 40}


@pytest.fixture(scope="module")
def mockup():
    return build_collections(sizes=SIZES)


def test_same_seed_writes_identical_files(tmp_path):
    for name in ("a", "b"):
        write_mockup(tmp_path / name / "data", tmp_path / name / "labels", seed=7, sizes=SIZES)
    files = sorted(path.relative_to(tmp_path / "a") for path in (tmp_path / "a").rglob("*") if path.is_file())
    assert files
    for file in files:
        assert (tmp_path / "a" / file).read_bytes() == (tmp_path / "b" / file).read_bytes()


def test_different_seed_changes_values():
    first, _ = build_collections(seed=1, sizes=SIZES)
    second, _ = build_collections(seed=2, sizes=SIZES)
    assert first["customers"][0]["IdNumber"] != second["customers"][0]["IdNumber"]


def test_every_declared_label_exists_in_documents(mockup):
    collections, _ = mockup
    for name, labels in PII_FIELDS.items():
        paths = {path for doc in collections[name] for path in field_paths(doc)}
        assert set(labels) <= paths


def test_every_field_has_exactly_one_label(mockup):
    collections, _ = mockup
    for name, docs in collections.items():
        labelled = [label["path"] for label in field_labels(name, docs)]
        assert len(labelled) == len(set(labelled))
        assert set(labelled) == {path for doc in docs for path in field_paths(doc)}


def test_contract_and_bill_keep_sample_shape(mockup):
    collections, _ = mockup
    contract, bill = collections["battery_contracts"][0], collections["battery_bills"][0]
    assert {"Batteries", "EnterpriseCustomer", "TaxRegistrationName", "IdNumber"} <= set(contract)
    assert {"PaidAt", "LeasingData", "LeasingFeeCutOffData", "SecureHash", "IDNumber"} <= set(bill)
    assert contract["Batteries"][0]["BatteryProblems"] == []
    assert isinstance(bill["Amount"], Decimal128)
    assert isinstance(bill["_id"], ObjectId)


def test_bson_types_survive_jsonl_round_trip(mockup):
    collections, _ = mockup
    options = json_util.RELAXED_JSON_OPTIONS.with_options(tz_aware=True)
    for doc in (collections["battery_contracts"][0], collections["battery_bills"][0]):
        assert json_util.loads(json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS), json_options=options) == doc


def test_keys_join_across_collections(mockup):
    collections, _ = mockup
    customers = {doc["CustomerId"]: doc for doc in collections["customers"]}
    contracts = {doc["ContractNo"]: doc for doc in collections["battery_contracts"]}
    for bill in collections["battery_bills"]:
        assert bill["IDNumber"] == customers[bill["CustomerId"]]["IdNumber"]
        assert contracts[bill["ContractNo"]]["CustomerId"] == bill["CustomerId"]


def test_enterprise_decides_tax_code_format(mockup):
    collections, _ = mockup
    enterprise = [doc for doc in collections["customers"] if doc["EnterpriseCustomer"]]
    individual = [doc for doc in collections["customers"] if not doc["EnterpriseCustomer"]]
    assert enterprise and individual
    assert all(doc["TaxRegistrationNumber"].startswith("0") for doc in enterprise)
    assert all(doc["TaxRegistrationNumber"].startswith("8") for doc in individual)
    assert all(doc["TaxRegistrationName"] == doc["FullName"] for doc in individual)


def test_hard_cases_are_present(mockup):
    collections, _ = mockup
    customers = collections["customers"]
    assert {len(doc["PhoneNumber"]) for doc in customers} == {10, 12}
    assert any(doc["FullName"].isupper() for doc in customers)
    assert all(re.fullmatch(r"\d{12}", doc["WaybillNo"]) for doc in collections["devices"])
    created_by = {doc["CreatedBy"] for doc in collections["battery_contracts"]}
    assert "Integration" in created_by and any("@" in value for value in created_by)
    assert any(doc["PaidAt"]["StoreAddress"] for doc in collections["battery_bills"])


def test_text_spans_point_at_the_right_entity(mockup):
    collections, text_spans = mockup
    notes = {doc["TicketNo"]: doc["Note"] for doc in collections["tickets"]}
    counts = Counter()
    for item in text_spans:
        note = notes[item["id"]]
        for span in item["labels"]:
            counts[span["type"]] += 1
            value = note[span["start"] : span["end"]]
            assert value and value == value.strip()
            if span["type"] == "EMAIL":
                assert "@" in value
            if span["type"] in ("CCCD", "BANK_ACCOUNT"):
                assert value.isdigit()
    expected = {"FULL_NAME", "PHONE", "EMAIL", "CCCD", "ADDRESS", "BANK_ACCOUNT", "TAX_CODE", "DOB", "CREDIT_CARD"}
    assert expected <= set(counts)


def _label(mockup, collection, path):
    collections, _ = mockup
    return next(item for item in field_labels(collection, collections[collection]) if item["path"] == path)


def test_labels_carry_legal_group(mockup):
    assert _label(mockup, "battery_bills", "IDNumber")["group"] == "co_ban"
    assert _label(mockup, "battery_bills", "PaidAt.AccountNumber")["group"] == "nhay_cam"
    assert _label(mockup, "battery_bills", "CardNumber")["group"] == "nhay_cam"
    assert _label(mockup, "battery_bills", "SecureHash")["group"] is None


def test_customer_keys_are_personal_only_for_individuals(mockup):
    for collection in ("customers", "battery_contracts", "battery_bills"):
        label = _label(mockup, collection, "CustomerId")
        assert (label["pii_type"], label["action"]) == ("CUSTOMER_ID", "HMAC")
        assert label["when"] == {"field": "EnterpriseCustomer", "equals": False}


def test_join_cccd_uses_hmac_and_plain_cccd_uses_mask(mockup):
    assert _label(mockup, "customers", "IdNumber")["action"] == "HMAC"
    assert _label(mockup, "battery_bills", "IDNumber")["action"] == "HMAC"
    assert _label(mockup, "customers", "c1")["action"] == "MASK"


def test_vehicle_ids_follow_context(mockup):
    for collection, path in (
        ("battery_contracts", "VehicleId"),
        ("battery_contracts", "Batteries[].Serial"),
        ("battery_contracts", "Batteries[].Stock"),
        ("battery_bills", "BatterySerial"),
    ):
        label = _label(mockup, collection, path)
        assert (label["action"], label["decision"]) == ("HMAC", "theo_ngu_canh")
    assert _label(mockup, "devices", "Serial")["pii_type"] is None
    assert _label(mockup, "devices", "Imei")["pii_type"] is None


def test_no_label_is_pending(mockup):
    collections, _ = mockup
    assert not any("pending" in item for name, docs in collections.items() for item in field_labels(name, docs))


def test_some_tickets_have_no_pii(mockup):
    _, text_spans = mockup
    assert any(not item["labels"] for item in text_spans)


def test_labels_and_catalog_never_contain_values(tmp_path):
    write_mockup(tmp_path / "data", tmp_path / "labels", sizes=SIZES)
    collections, _ = build_collections(sizes=SIZES)
    label_text = "".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "labels").rglob("*") if path.is_file()
    )
    for doc in collections["customers"]:
        for field in ("IdNumber", "Email", "PhoneNumber", "FullName"):
            assert doc[field] not in label_text


def test_catalog_lists_only_pii_fields(tmp_path):
    write_mockup(tmp_path / "data", tmp_path / "labels", sizes=SIZES)
    catalog = json.loads((tmp_path / "labels" / "catalog" / "battery_bills.json").read_text(encoding="utf-8"))
    paths = {field["path"] for field in catalog["fields"]}
    assert catalog["schemaVersion"] == 1
    assert "PaidAt.AccountNumber" in paths
    assert "PaidAt.AccountCashInBank" not in paths
