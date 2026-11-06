import json
from pathlib import Path

from mockup.heldout import (
    STYLES,
    heldout_names,
    random_names,
    rename_document,
    rename_path,
    segments_of,
    style_of,
)

LABELS = Path(__file__).resolve().parents[2] / "mockup/labels/fields.jsonl"


def _labels():
    with LABELS.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def _segments(collection):
    return segments_of(label["path"] for label in _labels() if label["collection"] == collection)


def test_names_stay_unique_within_a_collection():
    for collection in ("customers", "battery_contracts", "battery_bills", "tickets", "devices"):
        names = heldout_names(collection, _segments(collection))
        assert len(set(names.values())) == len(names)
        randomized = random_names(collection, _segments(collection), seed=1)
        assert len(set(randomized.values())) == len(randomized)


def test_every_pii_field_gets_a_new_name_and_every_style_is_used():
    styles = set()
    for label in _labels():
        if label["pii_type"] is None or label["collection"] == "app_events":
            continue
        segment = label["path"].split(".")[-1].removesuffix("[]")
        names = heldout_names(label["collection"], [segment])
        assert names[segment] != segment
        styles.add(style_of(label["collection"], segment))
    assert styles == set(STYLES)


def test_names_are_stable_and_random_depends_on_seed():
    segments = _segments("customers")
    assert heldout_names("customers", segments) == heldout_names("customers", segments)
    assert random_names("customers", segments, 1) != random_names("customers", segments, 2)


def test_rename_document_and_path_agree():
    names = {"Batteries": "pin", "Serial": "sn", "PaidAt": "tt", "AccountNumber": "stk"}
    document = {"_id": 1, "Batteries": [{"Serial": "x"}], "PaidAt": {"AccountNumber": "y"}}
    renamed = rename_document(document, names)
    assert renamed == {"_id": 1, "pin": [{"sn": "x"}], "tt": {"stk": "y"}}
    assert rename_path("Batteries[].Serial", names) == "pin[].sn"
    assert rename_path("PaidAt.AccountNumber", names) == "tt.stk"
    assert rename_path("_id", names) == "_id"
