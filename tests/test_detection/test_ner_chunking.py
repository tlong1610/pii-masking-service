"""Long free text is scanned in chunks under GLiNER's length limit, offsets mapped back to the full text."""

import re

import piimask.detection.ml_ner as ml_ner
from piimask.detection.ml_ner import MLNERScanner
from piimask.transform.mask_engine import redact_value


class _FakeGLiNER:
    """Stands in for GLiNER: tags "Bình" as a person; fails if a chunk exceeds the word limit."""

    def predict_entities(self, text: str, labels: list[str], threshold: float = 0.5) -> list[dict]:
        limit = ml_ner.MAX_CHUNK_TOKENS
        words = list(re.finditer(r"\w+(?:[-_]\w+)*|\S", text))
        if len(words) > limit:
            raise AssertionError(f"chunk of {len(words)} words exceeds {limit}")
        return [
            {"label": "person", "text": "Bình", "start": m.start(), "end": m.end(), "score": 0.9}
            for m in re.finditer("Bình", text)
        ]


def _scanner() -> MLNERScanner:
    scanner = MLNERScanner.__new__(MLNERScanner)
    scanner.model = _FakeGLiNER()
    scanner.labels = ["person"]
    scanner.threshold = 0.35
    return scanner


def test_long_text_is_chunked_and_offsets_point_into_full_text(monkeypatch):
    monkeypatch.setattr(ml_ner, "MAX_CHUNK_TOKENS", 20)
    text = " ".join(f"Câu số {i} giao hàng cho anh Bình ở kho." for i in range(30))
    matches = _scanner().scan_text(text)
    assert len(matches) == 30
    assert all(text[m.start : m.end] == "Bình" for m in matches)


def test_single_overlong_sentence_is_cut_between_words(monkeypatch):
    monkeypatch.setattr(ml_ner, "MAX_CHUNK_TOKENS", 10)
    text = " ".join(["chữ"] * 50) + " Bình"
    matches = _scanner().scan_text(text)
    assert [text[m.start : m.end] for m in matches] == ["Bình"]


def test_redact_value_fails_closed_when_ner_errors(monkeypatch):
    def boom(_text: str) -> str:
        raise RuntimeError("model failure")

    monkeypatch.setattr("piimask.transform.mask_engine.mask_text", boom)
    assert redact_value("Gọi 0912345678") == "[REDACTED]"
