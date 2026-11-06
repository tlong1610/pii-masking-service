import mongomock

from piimask.connectors.mongo_connector import MongoConnector


def _connector(documents):
    client = mongomock.MongoClient()
    client["src"]["khach"].insert_many(documents)
    return MongoConnector("mongodb://mockup", database_name="src", client=client)


def test_scanner_contract_keeps_real_path_and_marks_primary_key():
    tasks = _connector([{"_id": "k1", "contact": {"phone": "0912345678"}}]).to_scanner_contract()
    by_path = {task["field_path"]: task for task in tasks}
    assert by_path["contact.phone"]["column_profile"].column_name == "contact_phone"
    assert by_path["contact.phone"]["column_profile"].samples == ["0912345678"]
    assert by_path["_id"]["column_profile"].is_primary_key is True


def test_contract_covers_arrays_deep_fields_and_fields_in_late_documents():
    documents = [{"_id": index, "a": 1} for index in range(300)]
    documents[-1]["cuoi"] = {"b": {"c": {"d": {"e": "x"}}}}
    documents[-1]["mang"] = [{"so": "0912345678"}]
    tasks = _connector(documents).to_scanner_contract()
    by_path = {task["field_path"]: task["column_profile"] for task in tasks}
    assert by_path["cuoi.b.c.d.e"].samples == ["x"]
    assert by_path["mang[].so"].column_name == "mang_so"


def test_contract_can_be_limited_to_some_collections():
    connector = _connector([{"_id": 1, "a": 1}])
    assert connector.to_scanner_contract(collections=[]) == []
    assert connector.collection_names() == ["khach"]


def test_iter_documents_reads_every_document():
    connector = _connector([{"_id": index} for index in range(5)])
    assert len(list(connector.iter_documents("khach", batch_size=2))) == 5
