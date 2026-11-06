"""Che PII trong văn bản, dùng chung cho API và tool. Vị trí trả về luôn tính trên văn bản gốc."""

import json
import re
from dataclasses import dataclass

from piimask.detection.ner_orchestrator import NERPipelines, get_ner_pipeline

# Tên loại công bố trong hợp đồng API; các tầng phát hiện gọi họ tên bằng tên khác nhau.
_PUBLIC_TYPES = {"FULL_NAME": "NAME", "PERSON_NAME": "NAME"}
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


@dataclass(frozen=True)
class Entity:
    type: str
    start: int
    end: int


@dataclass(frozen=True)
class MaskedText:
    text: str
    entities: list[Entity]


def _render(
    text: str, entities: list[Entity], quoted: frozenset[Entity] = frozenset()
) -> tuple[str, list[tuple[int, int, Entity]]]:
    """Thay thực thể bằng thẻ; trả văn bản mới và vị trí từng thẻ trong văn bản mới."""
    pieces, tags, cursor, length = [], [], 0, 0
    for entity in entities:
        tag = f'"[{entity.type}]"' if entity in quoted else f"[{entity.type}]"
        pieces += [text[cursor : entity.start], tag]
        length += entity.start - cursor
        tags.append((length, length + len(tag), entity))
        length += len(tag)
        cursor = entity.end
    pieces.append(text[cursor:])
    return "".join(pieces), tags


def _to_original(position: int, tags: list[tuple[int, int, Entity]], *, is_end: bool) -> int:
    """Đổi vị trí trên văn bản đã che một phần về văn bản gốc. Vị trí nằm trong thẻ thì lấy biên thực thể."""
    shift = 0
    for tag_start, tag_end, entity in tags:
        if position < tag_start or (is_end and position == tag_start):
            break
        if position < tag_end or (is_end and position == tag_end):
            return entity.end if is_end else entity.start
        shift = entity.end - tag_end
    return position + shift


def _is_json(text: str) -> bool:
    if text.lstrip()[:1] not in ("{", "["):
        return False
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _render_json(text: str, entities: list[Entity]) -> str:
    """Thực thể nằm ngoài chuỗi JSON là số: thẻ phải có dấu nháy để JSON vẫn hợp lệ."""
    strings = [match.span() for match in _JSON_STRING.finditer(text)]
    numbers = [
        entity for entity in entities if not any(start <= entity.start and entity.end <= end for start, end in strings)
    ]
    masked = _render(text, entities, frozenset(numbers))[0]
    # Không trả JSON hỏng: lỗi ở đây để bên gọi chặn lại. Không đưa nội dung vào thông báo lỗi.
    json.loads(masked)
    return masked


def mask_text(text: str, keep: list[str] | None = None, pipeline: NERPipelines | None = None) -> MaskedText:
    """Che qua từng tầng phát hiện. Loại nằm trong keep giữ nguyên trong văn bản."""
    pipeline = pipeline or get_ner_pipeline()
    kept = set(keep or [])
    current, tags, entities = text, [], []
    for scanner in pipeline.tiers():
        for match in scanner.scan_text(current):
            pii_type = _PUBLIC_TYPES.get(match.pii_type, match.pii_type)
            if pii_type in kept:
                continue
            start = _to_original(match.start, tags, is_end=False)
            end = _to_original(match.end, tags, is_end=True)
            if any(entity.start <= start and end <= entity.end for entity in entities):
                continue
            entities = [entity for entity in entities if not (start <= entity.start and entity.end <= end)]
            entities.append(Entity(pii_type, start, end))
        entities.sort(key=lambda entity: entity.start)
        current, tags = _render(text, entities)
    if entities and _is_json(text):
        current = _render_json(text, entities)
    return MaskedText(current, entities)
