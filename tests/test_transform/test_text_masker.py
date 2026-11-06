import json

import pytest

from piimask.detection.ner_orchestrator import NERPipelines
from piimask.detection.regex_ner import EntityMatch
from piimask.transform.text_masker import Entity, mask_text

CONTRACT_TEXT = "Trạm của anh Nguyễn Văn A, gọi 0912345678, công tơ DEMO-001 B2 đọc 00420.1 bất thường"


def _pipeline(*names):
    return NERPipelines({"NAME": list(names)}, use_ml=False)


class _FixedTier:
    """Tầng giả trả đúng các vị trí đã khai trên văn bản nó nhận được."""

    def __init__(self, *spans):
        self.spans = spans

    def scan_text(self, text):
        return [EntityMatch(start=s, end=e, pii_type=t, text=text[s:e]) for s, e, t in self.spans]


class _Pipeline:
    def __init__(self, *tiers):
        self._tiers = tiers

    def tiers(self):
        return list(self._tiers)


def test_matches_contract_example():
    result = mask_text(CONTRACT_TEXT, ["METER_ID", "REGISTER", "METER_READING"], _pipeline("Nguyễn Văn A"))
    assert result.text == "Trạm của anh [NAME], gọi [PHONE], công tơ DEMO-001 B2 đọc 00420.1 bất thường"
    assert result.entities == [Entity("NAME", 13, 25), Entity("PHONE", 31, 41)]


def test_offsets_of_later_tiers_point_at_original_text():
    text = "gọi 0912345678 gặp Trần Thị B"
    result = mask_text(text, pipeline=_pipeline("Trần Thị B"))
    assert [text[entity.start : entity.end] for entity in result.entities] == ["0912345678", "Trần Thị B"]


def test_keep_leaves_that_type_in_text():
    result = mask_text(CONTRACT_TEXT, ["PHONE"], _pipeline("Nguyễn Văn A"))
    assert "0912345678" in result.text
    assert [entity.type for entity in result.entities] == ["NAME"]


def test_keep_uses_public_name_for_person_types():
    pipeline = _Pipeline(_FixedTier((0, 3, "PERSON_NAME")))
    assert mask_text("Lan đi", ["NAME"], pipeline).text == "Lan đi"
    assert mask_text("Lan đi", [], pipeline).text == "[NAME] đi"


def test_later_match_inside_a_tag_is_ignored():
    # Tầng sau nhận nhầm chữ PHONE trong thẻ của tầng trước.
    pipeline = _Pipeline(_FixedTier((4, 14, "PHONE")), _FixedTier((5, 10, "NAME")))
    result = mask_text("gọi 0912345678 nhé", pipeline=pipeline)
    assert result.text == "gọi [PHONE] nhé"
    assert result.entities == [Entity("PHONE", 4, 14)]


def test_later_match_across_a_tag_absorbs_it():
    # Văn bản sau tầng đầu: "a [PHONE] b"; tầng sau phủ cả thẻ và chữ b.
    pipeline = _Pipeline(_FixedTier((2, 12, "PHONE")), _FixedTier((2, 11, "ADDRESS")))
    result = mask_text("a 0912345678 b", pipeline=pipeline)
    assert result.text == "a [ADDRESS]"
    assert result.entities == [Entity("ADDRESS", 2, 14)]


def test_text_without_pii_is_unchanged():
    assert mask_text("không có gì", pipeline=_pipeline()).text == "không có gì"
    assert mask_text("", pipeline=_pipeline()).entities == []


def test_number_in_json_gets_quoted_tag():
    text = '{"cccd":123456789012,"amount":1500000}'
    result = mask_text(text, pipeline=_pipeline())
    assert json.loads(result.text) == {"cccd": "[CCCD]", "amount": 1500000}
    assert result.entities == [Entity("CCCD", 8, 20)]


def test_string_in_json_keeps_single_quotes_and_nested_json_stays_valid():
    text = '[{"a":{"phone":"gọi 0912345678 nhé"}},1]'
    assert json.loads(mask_text(text, pipeline=_pipeline()).text) == [{"a": {"phone": "gọi [PHONE] nhé"}}, 1]


def test_quote_inside_json_string_does_not_confuse_position():
    text = r'{"note":"a \"b\" 0912345678","n":123456789012}'
    assert json.loads(mask_text(text, pipeline=_pipeline()).text) == {"note": 'a "b" [PHONE]', "n": "[CCCD]"}


def test_text_that_only_looks_like_json_is_masked_as_text():
    assert mask_text("{gọi 0912345678", pipeline=_pipeline()).text == "{gọi [PHONE]"


def test_mask_that_would_break_json_fails_instead_of_returning_broken_text():
    # Thực thể chỉ phủ phần nguyên của số thực nên không thể thay mà giữ được JSON hợp lệ.
    with pytest.raises(ValueError) as failure:
        mask_text('{"a":123456789012.5}', pipeline=_pipeline())
    assert "123456789012" not in str(failure.value)
