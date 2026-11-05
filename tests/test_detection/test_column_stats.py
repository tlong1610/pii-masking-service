"""Thống kê phân bố chỉ ở dạng nhóm thô: không số đếm chính xác, không giá trị."""

from piimask.detection.column_stats import describe_distribution, ratios_from_counts
from piimask.schemas import ColumnProfile


def test_ratios_from_counts():
    assert ratios_from_counts(100, 80, 8) == (80, 0.1, 0.2)
    assert ratios_from_counts(0, 0, 0) == (None, None, None)
    assert ratios_from_counts(5, 0, 0) == (0, None, 1.0)


def test_too_few_values_gives_no_signal():
    # 3 people with 3 different titles look exactly like 3 names: say nothing.
    assert describe_distribution(3, 1.0, 0.0) is None
    assert describe_distribution(None, None, None) is None


def test_small_table_only_trusts_repetition():
    # 9 employees, 4 titles: repetition is visible even in a small table.
    assert "thấp: giá trị lặp lại nhiều" in describe_distribution(9, 4 / 9, 0.0)
    # 9 rows all different: could be names or just too few rows.
    assert "chưa kết luận được" in describe_distribution(9, 1.0, 0.0)


def test_large_table_buckets_without_exact_counts():
    text = describe_distribution(8_431, 0.0024, 0.31)
    assert "rất thấp" in text and "trống một phần" in text and "trên 1.000" in text
    assert "8431" not in text and "8.431" not in text and "0.0024" not in text


def test_mongo_profile_counts_distinct_and_missing_fields():
    import mongomock

    from piimask.connectors.mongo_connector import MongoConnector

    client = mongomock.MongoClient()
    titles = ["Sales Rep"] * 15 + ["Manager"] * 4 + ["CEO"]
    client["hr"]["employees"].insert_many(
        [{"name": f"Person {i}", "title": t} for i, t in enumerate(titles)] + [{"name": "No Title"} for _ in range(5)]
    )
    profile = MongoConnector("mongodb://fake", "hr", client=client).extract_database_profile()
    columns = {c.column_name: c for c in profile.tables[0].columns}

    assert columns["title"].profiled_values == 20
    assert columns["title"].distinct_ratio == 3 / 20
    assert columns["title"].null_ratio == 5 / 25
    assert columns["name"].distinct_ratio == 21 / 25
