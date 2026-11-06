"""Tính recall, precision từ nhãn chuẩn và kết quả phát hiện. Không phụ thuộc lõi hay nguồn dữ liệu."""

from collections import defaultdict

from piimask.detection.taxonomy import LegalGroup, legal_group

# Loại lõi trả về mà không phải kết luận "đây là PII".
NON_PII_TYPES = frozenset(
    {"NOT_PERSONAL_DATA", "TRACKING_CODE", "MONEY_ALONE", "TAX_CODE_ORG", "CITY", "EMPTY_COLUMN", "UNKNOWN"}
)


def _ratio(hit: int, total: int) -> float | None:
    return round(hit / total, 4) if total else None


def _summarize(rows: list[tuple[str, bool]], true_flags: int, false_flags: int) -> dict:
    """rows là (loại PII, bắt được không). Trả số tổng, số nhóm nhạy cảm và số theo từng loại."""
    by_type: dict[str, list[bool]] = defaultdict(list)
    for pii_type, found in rows:
        by_type[pii_type].append(found)

    sensitive = [found for pii_type, found in rows if legal_group(pii_type) == LegalGroup.NHAY_CAM]
    found_all = sum(found for _, found in rows)
    return {
        "recall": _ratio(found_all, len(rows)),
        "precision": _ratio(true_flags, true_flags + false_flags),
        "total": len(rows),
        "found": found_all,
        "false_positives": false_flags,
        "recall_nhay_cam": _ratio(sum(sensitive), len(sensitive)),
        "by_type": {
            pii_type: {"total": len(hits), "found": sum(hits), "recall": _ratio(sum(hits), len(hits))}
            for pii_type, hits in sorted(by_type.items())
        },
    }


def score_fields(gold: list[dict], predicted: dict[str, str | None]) -> dict:
    """gold: nhãn có 'key', 'pii_type'. predicted: key -> loại lõi trả (None nếu lõi chưa kết luận).

    Một trường tính là bắt được khi lõi kết luận là PII, loại khác nhãn vẫn tính vì giá trị vẫn được che.
    Đường dẫn lõi không nhìn thấy (ví dụ trường trong mảng) tính là bỏ sót.
    """

    def flagged(key: str) -> bool:
        pii_type = predicted.get(key)
        return pii_type is not None and pii_type not in NON_PII_TYPES

    gold_keys = {label["key"] for label in gold}
    positives = [label for label in gold if label["pii_type"] is not None]
    positive_keys = {label["key"] for label in positives}

    rows = [(label["pii_type"], flagged(label["key"])) for label in positives]
    missed = sorted(label["key"] for label in positives if not flagged(label["key"]))
    false_positives = sorted(key for key in predicted if flagged(key) and key not in positive_keys)
    summary = _summarize(rows, sum(found for _, found in rows), len(false_positives))
    return {
        **summary,
        "fields": len(gold_keys),
        "undecided": sum(1 for key in gold_keys if key in predicted and predicted[key] is None),
        "missed": missed,
        "false_positive_fields": false_positives,
    }


def _covered(span: dict, predictions: list[tuple[int, int]]) -> bool:
    """Thực thể chỉ tính là bắt được khi được che trọn; che một phần vẫn lộ giá trị."""
    position = span["start"]
    for start, end in sorted(predictions):
        if start <= position < end:
            position = end
    return position >= span["end"]


def score_spans(items: list[tuple[list[dict], list[tuple[int, int]]]]) -> dict:
    """items: mỗi văn bản một cặp (nhãn {type, start, end}, vị trí lõi tìm thấy (start, end))."""
    rows, true_flags, false_flags = [], 0, 0
    for labels, predictions in items:
        rows.extend((label["type"], _covered(label, predictions)) for label in labels)
        for start, end in predictions:
            if any(start < label["end"] and label["start"] < end for label in labels):
                true_flags += 1
            else:
                false_flags += 1
    return _summarize(rows, true_flags, false_flags)
