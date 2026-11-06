import sys
from unittest.mock import MagicMock

from piimask.detection.ml_ner import MLNERScanner


def test_ml_ner_scanner(monkeypatch):
    mock_model = MagicMock()
    mock_model.predict_entities.return_value = [
        {"start": 12, "end": 27, "text": "Phạm Nhật Vượng", "label": "person", "score": 0.98},
        {"start": 57, "end": 65, "text": "Vingroup", "label": "organization", "score": 0.95},
        {"start": 70, "end": 79, "text": "Nha Trang", "label": "location", "score": 0.92},
    ]
    fake_gliner_cls = MagicMock()
    fake_gliner_cls.from_pretrained.return_value = mock_model
    monkeypatch.setitem(sys.modules, "gliner", MagicMock(GLiNER=fake_gliner_cls))

    scanner = MLNERScanner()

    # Text đã bị loại bỏ SĐT/Email từ Tầng 1 và Tầng 2, chỉ còn văn bản thuần.
    text = "Hôm qua anh Phạm Nhật Vượng có ghé thăm cơ sở của tập đoàn Vingroup tại Nha Trang."

    matches = scanner.scan_text(text)

    assert len(matches) == 3

    # Sort matches to assert in order
    matches_sorted = sorted(matches, key=lambda x: x.start)

    assert matches_sorted[0].pii_type == "PERSON_NAME"
    assert "Phạm Nhật Vượng" in matches_sorted[0].text

    assert matches_sorted[1].pii_type == "ORGANIZATION"
    assert "Vingroup" in matches_sorted[1].text

    assert matches_sorted[2].pii_type == "LOCATION"
    assert "Nha Trang" in matches_sorted[2].text
