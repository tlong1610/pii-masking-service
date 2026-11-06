import mongomock

from piimask.connectors.mongo_connector import (
    MongoConnector,
    _flatten_document,
    _infer_data_type,
)


def test_flatten_document():
    nested = {
        "_id": "ALFKI",
        "contact": {
            "phone": "0327540543",
            "email": "alfki@example.vn",
        },
        "identity": {
            "cccd": "033254456184",
            "nested_level2": {
                "tag": "vip",
            },
        },
        "status": "active",
    }
    flattened = _flatten_document(nested)

    assert flattened["_id"] == "ALFKI"
    assert flattened["contact.phone"] == "0327540543"
    assert flattened["contact.email"] == "alfki@example.vn"
    assert flattened["identity.cccd"] == "033254456184"
    assert flattened["identity.nested_level2.tag"] == "vip"
    assert flattened["status"] == "active"

    # Test level 3 is preserved as object when max_depth = 2
    deep_nested = {
        "level1": {
            "level2": {
                "level3": {
                    "level4": "deep_val"
                }
            }
        }
    }
    flattened_max2 = _flatten_document(deep_nested, max_depth=2)
    # Path has 2 dots: level1.level2.level3 (2 levels of nesting)
    assert "level1.level2.level3" in flattened_max2
    assert flattened_max2["level1.level2.level3"] == {"level4": "deep_val"}
    assert "level1.level2.level3.level4" not in flattened_max2


def test_infer_data_type():
    assert _infer_data_type(True) == "boolean"
    assert _infer_data_type(42) == "integer"
    assert _infer_data_type(3.14) == "float"
    assert _infer_data_type("text") == "string"
    assert _infer_data_type(["a", "b"]) == "array"
    assert _infer_data_type({"k": "v"}) == "object"


def test_scanner_contract_keeps_real_path_and_marks_primary_key():
    client = mongomock.MongoClient()
    client["src"]["khach"].insert_one({"_id": "k1", "contact": {"phone": "0912345678"}})
    tasks = MongoConnector("mongodb://mockup", database_name="src", client=client).to_scanner_contract()

    by_path = {task["field_path"]: task for task in tasks}
    assert by_path["contact.phone"]["column_profile"].column_name == "contact_phone"
    assert by_path["contact.phone"]["column_profile"].samples == ["0912345678"]
    assert by_path["_id"]["column_profile"].is_primary_key is True


def test_iter_documents_reads_every_document():
    client = mongomock.MongoClient()
    client["src"]["khach"].insert_many([{"_id": index} for index in range(5)])
    connector = MongoConnector("mongodb://mockup", database_name="src", client=client)
    assert len(list(connector.iter_documents("khach", batch_size=2))) == 5
