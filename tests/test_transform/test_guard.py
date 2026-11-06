"""Lớp chặn cuối cho ô sắp giữ nguyên."""

from piimask.policy import routine_formats
from piimask.transform.mask_engine import guard_value


def test_masks_only_the_pii_part():
    assert guard_value("Showroom gọi 0912345678 nhé") == "Showroom gọi [PHONE] nhé"


def test_catches_every_regex_type():
    assert guard_value("kh@example.com") == "[EMAIL]"
    assert guard_value("001099012345") == "[CCCD]"
    assert guard_value("password=Abc123!") == "password=[PASSWORD]"
    assert guard_value("Bearer abcdefgh") == "Bearer [TOKEN]"


def test_leaves_other_values_alone():
    for value in ("Showroom Demo 12", "", None, 1500, 12.5, True):
        assert guard_value(value) == value


def test_exempt_type_stays_but_other_types_are_caught():
    assert guard_value("400691172582", ("CCCD",)) == "400691172582"
    assert guard_value("gọi 0912345678", ("CCCD",)) == "gọi [PHONE]"


def test_failure_never_returns_the_value(monkeypatch):
    def boom(*args):
        raise RuntimeError("0912345678")

    monkeypatch.setattr("piimask.transform.mask_engine._guard_text", boom)
    assert guard_value("gọi 0912345678") == "***"


def test_routine_formats_needs_most_samples_to_match_whole():
    assert routine_formats(["400691172582"] * 6 + ["ABC"] * 4) == ("CCCD",)
    assert routine_formats(["400691172582"] + ["ABC"] * 9) == ()
    assert routine_formats(["mã 400691172582 hôm nay"] * 10) == ()
    assert routine_formats([]) == ()
