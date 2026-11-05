"""Entity-level redaction for free-text values (Luồng B): Regex -> Dictionary -> ML NER, mask-and-pass.

Used by the REDACT action when building snapshots and by the scanner to tell whether a free-text
column carries PII. Only entity *types* ever leave this module for metadata; matched text stays in memory.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable

from piimask.detection.dict_ner import DictionaryNERScanner
from piimask.detection.redactor import TextRedactor
from piimask.detection.regex_ner import EntityMatch, RegexNERScanner

logger = logging.getLogger(__name__)


class NERPipelines:
    """
    Luồng Redaction Phễu lọc 3 tầng (Entity-Level Mask-and-Pass).
    Quá trình: Text gốc -> Regex -> Mask -> Dict -> Mask -> ML (GLiNER Zero-Shot) -> Mask -> Text sạch.
    use_ml=False skips the model tier (no model download, regex + dictionary only).
    """
    def __init__(self, dict_configs: dict | None = None, *, use_ml: bool = True, model_name: str | None = None):
        self.regex_scanner = RegexNERScanner()
        self.dict_scanner = DictionaryNERScanner()
        self.ml_scanner = None
        if use_ml:
            from piimask.detection.ml_ner import MLNERScanner

            self.ml_scanner = MLNERScanner(model_name) if model_name else MLNERScanner()

        # Nạp từ điển mẫu nếu có
        if dict_configs:
            for pii_type, keywords in dict_configs.items():
                self.dict_scanner.load_dictionary(pii_type, keywords)

    def tiers(self) -> list:
        tiers: list = [self.regex_scanner, self.dict_scanner]
        if self.ml_scanner is not None:
            tiers.append(self.ml_scanner)
        return tiers

    def redact_with_matches(self, text: str) -> tuple[str, list[EntityMatch]]:
        """Redact text tier by tier; return the clean text and every entity found (in memory only)."""
        if not text:
            return text, []
        found: list[EntityMatch] = []
        for scanner in self.tiers():
            matches = scanner.scan_text(text)
            found.extend(matches)
            text = TextRedactor.redact(text, matches)
        return text, found

    def redact_document(self, text: str) -> str:
        """
        Thực hiện toàn bộ luồng pipeline để làm sạch một đoạn văn bản.
        """
        return self.redact_with_matches(text)[0]


_pipeline: NERPipelines | None = None
_pipeline_lock = threading.Lock()


def _load_dictionary(path: str) -> dict[str, list[str]]:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): [str(v) for v in values] for k, values in data.items()}
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("NER dictionary not loaded (%s): %s", path, type(exc).__name__)
        return {}


def get_ner_pipeline() -> NERPipelines:
    """Process-wide pipeline built from settings; the ML tier is loaded once, lazily, only if enabled."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            from piimask.config import get_settings

            settings = get_settings()
            dictionary = _load_dictionary(settings.ner_dictionary_path)
            try:
                _pipeline = NERPipelines(dictionary, use_ml=settings.enable_ner, model_name=settings.ner_model_name)
            except Exception as exc:
                if settings.enable_ner:
                    logger.warning("ML NER unavailable (%s); free-text redaction runs regex/dictionary only",
                                   type(exc).__name__)
                _pipeline = NERPipelines(dictionary, use_ml=False)
    return _pipeline


def reset_ner_pipeline() -> None:
    """Drop the cached pipeline (tests / settings change)."""
    global _pipeline
    with _pipeline_lock:
        _pipeline = None


def redact_free_text(text: str) -> str:
    """Replace every detected entity with its type tag, e.g. 'gọi 0912345678' -> 'gọi [PHONE]'."""
    return get_ner_pipeline().redact_document(text)


def detect_entity_types(samples: Iterable[object]) -> tuple[list[str], int]:
    """Entity types found across samples and how many samples had one. Never returns matched text."""
    pipeline = get_ner_pipeline()
    types: set[str] = set()
    hits = 0
    for sample in samples:
        if not isinstance(sample, str) or not sample.strip():
            continue
        _, matches = pipeline.redact_with_matches(sample)
        if matches:
            hits += 1
            types.update(m.pii_type for m in matches)
    return sorted(types), hits
