import mongomock
import pytest

from mockup.load_perf import PERF_COLLECTION, RARE_FIELDS, RareField, load_perf, perf_database, rare_values


def test_loads_requested_count_in_batches():
    client = mongomock.MongoClient()
    assert load_perf(client, "p", count=25, batch_size=10) == 25
    assert client["p"][PERF_COLLECTION].find_one()["FullName"]


def test_load_twice_replaces():
    client = mongomock.MongoClient()
    load_perf(client, "p", count=5)
    assert load_perf(client, "p", count=5) == 5


def test_refuses_database_with_foreign_collections():
    client = mongomock.MongoClient()
    client["p"]["orders"].insert_one({"a": 1})
    with pytest.raises(ValueError, match="orders"):
        load_perf(client, "p", count=1)


def test_perf_database_is_separate_from_labelled_mockup():
    assert perf_database("mockup") == "mockup_perf"


def _late_phone(path, start=30):
    return RareField(path, "PHONE", "ca thử", start, 10, lambda v: v.phone())


def test_rare_field_exists_only_in_planned_documents():
    client = mongomock.MongoClient()
    load_perf(client, "p", count=50, rare_fields=[_late_phone("Late.Phone")])
    documents = list(client["p"][PERF_COLLECTION].find({}))
    planted = rare_values([_late_phone("Late.Phone")], 50)["Late.Phone"]
    assert sorted(planted) == [30, 40]
    assert [index for index, doc in enumerate(documents) if "Late" in doc] == [30, 40]
    assert documents[30]["Late"]["Phone"] == planted[30]


def test_rare_field_in_array_and_template():
    field = RareField("Lien[].Note", "PHONE", "ca thử", 0, 10, lambda v: v.phone(), "gọi {value}")
    client = mongomock.MongoClient()
    load_perf(client, "p", count=5, rare_fields=[field])
    value = rare_values([field], 5)["Lien[].Note"][0]
    assert client["p"][PERF_COLLECTION].find_one()["Lien"] == [{"Note": f"gọi {value}"}]


def test_planting_does_not_change_other_documents():
    plain, planted = mongomock.MongoClient(), mongomock.MongoClient()
    load_perf(plain, "p", count=20, rare_fields=[])
    load_perf(planted, "p", count=20, rare_fields=[_late_phone("Late", start=5)])
    names = [[doc["FullName"], doc["Amount"]] for doc in plain["p"][PERF_COLLECTION].find({})]
    assert names == [[doc["FullName"], doc["Amount"]] for doc in planted["p"][PERF_COLLECTION].find({})]


def test_default_rare_fields_cover_deep_and_sparse_cases():
    assert sum(field.start >= 50_000 for field in RARE_FIELDS) >= 5
    assert sum(field.start < 100 for field in RARE_FIELDS) == 2
    assert all(field.every >= 250 for field in RARE_FIELDS)
