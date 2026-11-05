import mongomock
import pytest

from mockup.generate import write_mockup
from mockup.load_mongo import load_mockup

SIZES = {"customers": 40, "battery_bills": 20, "tickets": 20, "devices": 5, "file_rows": 10, "log_lines": 10}


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    root = tmp_path_factory.mktemp("mockup")
    write_mockup(root / "data", root / "labels", seed=3, sizes=SIZES)
    return root / "data"


def test_load_inserts_every_collection(data_dir):
    client = mongomock.MongoClient()
    counts = load_mockup(client, "mockup", data_dir)
    assert counts["customers"] == 40
    assert client["mockup"]["battery_bills"].count_documents({}) == 20


def test_load_twice_replaces_instead_of_duplicating(data_dir):
    client = mongomock.MongoClient()
    load_mockup(client, "mockup", data_dir)
    load_mockup(client, "mockup", data_dir)
    assert client["mockup"]["customers"].count_documents({}) == 40


def test_load_refuses_database_with_foreign_collections(data_dir):
    client = mongomock.MongoClient()
    client["mockup"]["orders"].insert_one({"a": 1})
    with pytest.raises(ValueError, match="orders"):
        load_mockup(client, "mockup", data_dir)
    assert client["mockup"].list_collection_names() == ["orders"]


def test_load_reports_missing_data(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_mockup(mongomock.MongoClient(), "mockup", tmp_path)
