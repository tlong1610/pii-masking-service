import json

from eval.history import record, regressions, summarize_sections


def _baseline(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"sections": {"a": {"recall": 0.5}}}), encoding="utf-8")
    return path


def test_record_adds_part_and_keeps_baseline(tmp_path):
    path = _baseline(tmp_path)
    record(path, "muc-1", "small", {"x": 1})
    record(path, "muc-1", "large", {"y": 2})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["sections"] == {"a": {"recall": 0.5}}
    assert data["history"] == [{"label": "muc-1", "small": {"x": 1}, "large": {"y": 2}}]


def test_record_replaces_same_part(tmp_path):
    path = _baseline(tmp_path)
    record(path, "m", "small", {"x": 1})
    record(path, "m", "small", {"x": 2})
    assert json.loads(path.read_text(encoding="utf-8"))["history"] == [{"label": "m", "small": {"x": 2}}]


def test_regressions_only_reports_drops():
    current = {"a": {"recall": 0.4, "precision": 0.9}, "b": {"recall": 0.1}}
    previous = {"a": {"recall": 0.5, "precision": 0.8}}
    assert regressions(current, previous) == ["a.recall: 50.0% -> 40.0%"]


def test_summarize_keeps_only_totals():
    section = {"recall": 0.5, "precision": 0.5, "recall_nhay_cam": None, "by_type": {}, "missed": ["x"]}
    summary = summarize_sections({"a": section})
    assert "missed" not in summary["a"] and summary["a"]["recall"] == 0.5
