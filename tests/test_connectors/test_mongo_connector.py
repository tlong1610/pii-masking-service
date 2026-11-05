"""
Unit tests for MongoConnector and schema flattening.
"""


from piimask.connectors.mongo_connector import (
    MongoConnector,
    _flatten_document,
    _infer_data_type,
)
from piimask.schemas import DatabaseProfile


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


def test_mongo_connector_profile_extraction(live_mongo):
    """
    Connects to the MongoDB container and validates extracted profile structure.
    """
    connector = MongoConnector()
    profile = connector.extract_database_profile(sample_size=3)

    assert isinstance(profile, DatabaseProfile)
    assert profile.database_name == "mydatabase"

    table_names = [t.table_name for t in profile.tables]
    assert "customers" in table_names
    assert "orders" in table_names

    customers_table = next(t for t in profile.tables if t.table_name == "customers")
    cust_cols = {c.column_name: c for c in customers_table.columns}
    assert "_id" in cust_cols
    assert cust_cols["_id"].is_primary_key is True
    assert cust_cols["_id"].system_recommendation == "HASHING"
    assert "identity.cccd" in cust_cols
    assert "contact.email" in cust_cols

    orders_table = next(t for t in profile.tables if t.table_name == "orders")
    ord_cols = {c.column_name: c for c in orders_table.columns}
    assert "_id" in ord_cols
    assert "customer_id" in ord_cols
    assert ord_cols["customer_id"].is_foreign_key is True
    assert ord_cols["customer_id"].system_recommendation == "HASHING"
    assert "pii_ext.customer_cccd" in ord_cols

    # Check relations
    assert len(orders_table.relations) >= 2
    rel_targets = [(r.from_column, r.to_table, r.to_column) for r in orders_table.relations]
    assert ("customer_id", "customers", "_id") in rel_targets
    assert ("pii_ext.customer_cccd", "customers", "identity.cccd") in rel_targets


def test_mongo_scanner_contract(live_mongo):
    """
    Validates inspect_scope, profile_fields, and to_scanner_contract methods,
    and proves seamless consumption by RuleBasedScanner.
    """
    from piimask.detection.rule_engine import RuleBasedScanner
    from piimask.detection.taxonomy import PIIType

    connector = MongoConnector()

    # 1. inspect_scope
    scopes = connector.inspect_scope()
    assert len(scopes) == 2
    scope_names = [s["collection_name"] for s in scopes]
    assert "customers" in scope_names
    assert "orders" in scope_names

    # 2. profile_fields
    fields = connector.profile_fields()
    assert len(fields) >= 35  # 17 in customers + 18 in orders
    field_names = [f.column_name for f in fields]
    assert "identity.cccd" in field_names
    assert "contact.email" in field_names
    assert "pii_ext.customer_cccd" in field_names

    # 3. to_scanner_contract
    tasks = connector.to_scanner_contract(sample_size=3)
    assert len(tasks) == len(fields)
    assert all("column_profile" in t and "field_path" in t for t in tasks)

    # 4. Scanner execution on the converted contract
    scanner = RuleBasedScanner()
    scan_results = []
    for task in tasks:
        col = task["column_profile"]
        res = scanner.tier1_static_filter(col)
        inferred = res.inferred_pii_type if res else PIIType.UNKNOWN.value
        action = res.recommended_action if res else "KEEP"
        scan_results.append((task["field_path"], inferred, action))

    # Assert critical PII fields are properly detected
    detected_dict = {path: pii for path, pii, _ in scan_results}
    assert detected_dict.get("identity.cccd") == PIIType.CCCD.value
    assert detected_dict.get("pii_ext.customer_cccd") == PIIType.CCCD.value
    assert detected_dict.get("contact.email") == PIIType.EMAIL.value

