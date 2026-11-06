import sys
from unittest.mock import MagicMock

from piimask.detection.ner_orchestrator import NERPipelines
from piimask.transform.text_masker import mask_text


def test_pipeline(monkeypatch):
    mock_model = MagicMock()
    mock_model.predict_entities.return_value = [
        {"start": 12, "end": 27, "text": "Phạm Nhật Vượng", "label": "person", "score": 0.98},
    ]
    fake_gliner_cls = MagicMock()
    fake_gliner_cls.from_pretrained.return_value = mock_model
    monkeypatch.setitem(sys.modules, "gliner", MagicMock(GLiNER=fake_gliner_cls))

    # Từ điển giả lập
    my_dict = {"LOCATION": ["Nha Trang", "Hà Nội", "Hồ Chí Minh"], "ORGANIZATION": ["Vingroup", "VinFast"]}

    pipeline = NERPipelines(dict_configs=my_dict)

    # Text tổng hợp chứa đủ các thành phần:
    # 0901234567 (PHONE) -> Regex
    # nguyen.van.a@gmail.com (EMAIL) -> Regex
    # Vingroup (ORG) -> Dict
    # Phạm Nhật Vượng (PERSON) -> ML
    raw_text = "Hôm qua anh Phạm Nhật Vượng có ghé thăm cơ sở của tập đoàn Vingroup tại Nha Trang. Hãy liên hệ qua số 0901234567 hoặc email vuong.pn@vingroup.com để biết thêm."

    clean_text = mask_text(raw_text, pipeline=pipeline).text

    # Assertions
    assert "[NAME]" in clean_text
    assert "[ORGANIZATION]" in clean_text
    assert "[LOCATION]" in clean_text
    assert "[PHONE]" in clean_text
    assert "[EMAIL]" in clean_text
