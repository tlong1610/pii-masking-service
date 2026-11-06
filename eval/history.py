"""Ghi số đo của từng lần sửa detector vào baseline.json, cạnh baseline gốc để so sánh."""

import json
from pathlib import Path

_METRICS = ("recall", "precision", "recall_nhay_cam")


def summarize_sections(sections: dict) -> dict:
    keep = (*_METRICS, "found", "total", "false_positives")
    return {name: {key: section.get(key) for key in keep} for name, section in sections.items()}


def record(baseline_path: Path, label: str, part: str, data: dict) -> None:
    """Thêm hoặc thay phần 'part' của mốc 'label'. Baseline gốc không đổi."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    history = baseline.setdefault("history", [])
    entry = next((item for item in history if item["label"] == label), None)
    if entry is None:
        entry = {"label": label}
        history.append(entry)
    entry[part] = data
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def regressions(current: dict, previous: dict) -> list[str]:
    """Các số tụt so với mốc trước, chỉ so các phần có ở cả hai."""
    found = []
    for name, section in current.items():
        old = previous.get(name)
        if not old:
            continue
        for metric in _METRICS:
            before, after = old.get(metric), section.get(metric)
            if before is not None and after is not None and after < before:
                found.append(f"{name}.{metric}: {before:.1%} -> {after:.1%}")
    return found
