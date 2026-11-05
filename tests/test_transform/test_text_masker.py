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
