from eval.metrics import score_fields, score_spans


def _gold(*rows):
    return [{"key": key, "pii_type": pii_type} for key, pii_type in rows]


def test_field_found_even_when_type_differs():
    result = score_fields(_gold(("a.acc", "BANK_ACCOUNT")), {"a.acc": "CREDIT_CARD"})
    assert result["recall"] == 1.0
    assert result["recall_nhay_cam"] == 1.0


def test_undecided_field_counts_as_missed():
    result = score_fields(_gold(("a.cccd", "CCCD")), {"a.cccd": None})
    assert result["recall"] == 0.0
    assert result["undecided"] == 1
    assert result["missed"] == ["a.cccd"]


def test_field_invisible_to_core_counts_as_missed():
    result = score_fields(_gold(("a.items[].serial", "VIN")), {"a.items": "NOT_PERSONAL_DATA"})
    assert result["missed"] == ["a.items[].serial"]


def test_non_pii_conclusion_is_not_flagged():
    result = score_fields(
        _gold(("a.id", "CUSTOMER_ID"), ("a.fee", None)), {"a.id": "NOT_PERSONAL_DATA", "a.fee": "MONEY_ALONE"}
    )
    assert result["recall"] == 0.0
    assert result["false_positives"] == 0


def test_false_positive_lowers_precision():
    gold = _gold(("a.phone", "PHONE"), ("a.waybill", None))
    result = score_fields(gold, {"a.phone": "PHONE", "a.waybill": "CCCD"})
    assert result["precision"] == 0.5
    assert result["false_positive_fields"] == ["a.waybill"]


def test_no_flag_leaves_precision_undefined():
    assert score_fields(_gold(("a.x", None)), {"a.x": None})["precision"] is None


def test_sensitive_recall_only_counts_sensitive_types():
    gold = _gold(("a.card", "CREDIT_CARD"), ("a.name", "FULL_NAME"))
    result = score_fields(gold, {"a.card": None, "a.name": "FULL_NAME"})
    assert result["recall"] == 0.5
    assert result["recall_nhay_cam"] == 0.0


def test_span_needs_full_coverage():
    label = {"type": "PHONE", "start": 5, "end": 15}
    assert score_spans([([label], [(5, 15)])])["recall"] == 1.0
    assert score_spans([([label], [(5, 10)])])["recall"] == 0.0
    assert score_spans([([label], [(3, 10), (10, 20)])])["recall"] == 1.0


def test_span_outside_labels_is_false_positive():
    label = {"type": "PHONE", "start": 5, "end": 15}
    result = score_spans([([label], [(5, 15), (30, 42)]), ([], [(1, 13)])])
    assert result["precision"] == 0.3333
    assert result["false_positives"] == 2
