import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import mongomock
import pytest

from eval.metrics import score_catalog
from mockup.generate import build_collections
from piimask.connectors.mongo_connector import MongoConnector
from tool.catalog import build_catalogs, write_catalogs

SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/api/pii-catalog-v1.schema.json").read_text(encoding="utf-8")
)
SIZES = {"customers": 30, "battery_bills": 30, "tickets": 20, "devices": 10}
PHONE, CCCD = "0912000111", "079199912345"


@pytest.fixture(scope="module")
def connector():
    collections, _ = build_collections(seed=9, sizes=SIZES)
    client = mongomock.MongoClient()
    for name, documents in collections.items():
        client["src"][name].insert_many(documents)
    return MongoConnector("mongodb://mockup", database_name="src", client=client)


@pytest.fixture(scope="module")
def catalogs(connector):
    return build_catalogs(connector, frozenset({"idnumber"}), enterprise_flag="EnterpriseCustomer")


def _fields(catalogs, collection):
    return {field["path"]: field for field in catalogs[collection]["fields"]}


def test_schema_itself_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_every_generated_catalog_matches_schema(catalogs):
    assert set(catalogs) == {"customers", "battery_contracts", "battery_bills", "tickets", "devices"}
    for catalog in catalogs.values():
        jsonschema.validate(catalog, SCHEMA)


def test_schema_rejects_values_and_unknown_actions(catalogs):
    catalog = json.loads(json.dumps(catalogs["customers"]))
    catalog["fields"][0]["sample"] = "0912345678"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, SCHEMA)
    catalog = json.loads(json.dumps(catalogs["customers"]))
    catalog["fields"][0]["action"] = "NULLIFY"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, SCHEMA)


def test_field_entries_carry_type_action_group_confidence_and_condition(catalogs):
    fields = _fields(catalogs, "customers")
    assert fields["PhoneNumber"]["pii_type"] == "PHONE"
    assert fields["PhoneNumber"]["action"] == "PARTIAL"
    assert fields["PhoneNumber"]["group"] == "co_ban"
    assert fields["PhoneNumber"]["confidence"] == 1.0
    assert fields["IdNumber"]["action"] == "HMAC"
    assert fields["CustomerId"]["when"] == {"field": "EnterpriseCustomer", "equals": False}
    assert "when" not in fields["PhoneNumber"]


def test_non_pii_fields_are_listed_so_new_fields_can_be_told_apart(catalogs):
    fields = _fields(catalogs, "battery_bills")
    assert fields["Amount"]["action"] == "KEEP" and fields["Amount"]["pii_type"] is None
    assert "PaidAt.AccountNumber" in fields


def test_devices_serial_is_kept_by_context(catalogs):
    fields = _fields(catalogs, "devices")
    assert fields["Serial"]["action"] == "KEEP"
    assert fields["Serial"]["reason"] == "khong_gan_voi_nguoi"


def test_array_and_scalar_array_paths(catalogs):
    assert "Batteries[].Serial" in _fields(catalogs, "battery_contracts")
    assert "PaymentMethodHistory[].value" in _fields(catalogs, "battery_bills")


def test_fields_are_sorted_and_output_is_stable(connector):
    stamp = datetime(2026, 11, 6, tzinfo=UTC)
    first = build_catalogs(connector, generated_at=stamp)
    second = build_catalogs(connector, generated_at=stamp)
    assert first == second
    paths = [field["path"] for field in first["customers"]["fields"]]
    assert paths == sorted(paths)


def test_written_files_match_schema_and_hold_no_values(tmp_path):
    client = mongomock.MongoClient()
    client["src"]["khach"].insert_one({"PhoneNumber": PHONE, "IdNumber": CCCD, "Note": f"gọi {PHONE}"})
    connector = MongoConnector("mongodb://mockup", database_name="src", client=client)
    (path,) = write_catalogs(build_catalogs(connector), tmp_path)
    text = path.read_text(encoding="utf-8")
    jsonschema.validate(json.loads(text), SCHEMA)
    assert PHONE not in text and CCCD not in text


def test_catalog_score_flags_pii_marked_keep_and_missing_fields():
    gold = [
        {"key": "a.x", "pii_type": "PHONE", "action": "PARTIAL"},
        {"key": "a.y", "pii_type": "EMAIL", "action": "HMAC", "when": {"field": "f", "equals": False}},
        {"key": "a.z", "pii_type": None, "action": "KEEP"},
        {"key": "a.w", "pii_type": "VIN", "action": "HMAC"},
        {"key": "a.t", "pii_type": "FREE_TEXT", "action": "REDACT"},
    ]
    fields = {
        "a.x": {"action": "PARTIAL"},
        "a.y": {"action": "KEEP"},
        "a.z": {"action": "KEEP"},
        "a.moi": {"action": "MASK"},
    }
    result = score_catalog(gold, fields)
    assert result["fields"] == 4 and result["missing"] == 1
    assert result["action_accuracy"] == 0.5
    assert result["pii_marked_keep_fields"] == ["a.w", "a.y"]
    assert result["extra_fields"] == ["a.moi"]
