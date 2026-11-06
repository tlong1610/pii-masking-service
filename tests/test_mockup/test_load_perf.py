import mongomock
import pytest

from mockup.load_perf import PERF_COLLECTION, load_perf, perf_database


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
