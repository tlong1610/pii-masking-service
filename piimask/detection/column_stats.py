"""Column distribution stats for the LLM tier: computed in the source DB, sent only as coarse buckets.

Only ratios and size buckets leave this module. Never min/max, most-common values or histograms (those are
values), and never an exact row count (business-sensitive). Stats are a hint, not a rule: first-name or
surname columns repeat a lot yet are still personal names, so a low ratio must never downgrade one.
"""

from __future__ import annotations

# Rows examined per column; enough for a stable ratio without a full scan of big tables.
STATS_ROW_LIMIT = 10_000
# Below this many values nothing is said (3 people, 3 titles -> both look unique, neither repeats).
MIN_VALUES_FOR_STATS = 5
# Below this, only "repeats a lot" is trusted (9 employees with 4 titles is clearly not a name column);
# "all different" may just mean too few rows.
MIN_VALUES_FOR_HIGH_RATIO = 50


def ratios_from_counts(n_rows: int, n_non_null: int, n_distinct: int) -> tuple[int | None, float | None, float | None]:
    """(profiled_values, distinct_ratio, null_ratio) from DB counts; None where undefined."""
    if n_rows <= 0:
        return None, None, None
    null_ratio = (n_rows - n_non_null) / n_rows
    distinct_ratio = n_distinct / n_non_null if n_non_null > 0 else None
    return n_non_null, distinct_ratio, null_ratio


def _size_bucket(values: int) -> str:
    if values < MIN_VALUES_FOR_HIGH_RATIO:
        return "ít (dưới 50 giá trị)"
    if values < 1000:
        return "vừa (50-1.000 giá trị)"
    return "nhiều (trên 1.000 giá trị)"


def _distinct_bucket(ratio: float) -> str:
    if ratio < 0.05:
        return "rất thấp: vài giá trị lặp lại rất nhiều lần"
    if ratio < 0.5:
        return "thấp: giá trị lặp lại nhiều"
    if ratio < 0.9:
        return "trung bình"
    return "rất cao: gần như mỗi dòng một giá trị khác"


def _null_bucket(ratio: float) -> str:
    if ratio < 0.05:
        return "hầu như không trống"
    if ratio < 0.5:
        return "trống một phần"
    if ratio < 0.95:
        return "phần lớn trống"
    return "gần như trống hoàn toàn"


def describe_distribution(
    profiled_values: int | None,
    distinct_ratio: float | None,
    null_ratio: float | None,
) -> str | None:
    """Coarse, value-free description for the prompt, or None when there are too few values to mean anything."""
    if profiled_values is None or distinct_ratio is None or profiled_values < MIN_VALUES_FOR_STATS:
        return None
    if profiled_values < MIN_VALUES_FOR_HIGH_RATIO and distinct_ratio >= 0.5:
        distinct = "chưa kết luận được (quá ít dòng để thấy lặp lại)"
    else:
        distinct = _distinct_bucket(distinct_ratio)
    parts = [f"số giá trị: {_size_bucket(profiled_values)}", f"tỷ lệ giá trị khác nhau: {distinct}"]
    if null_ratio is not None:
        parts.append(f"ô trống: {_null_bucket(null_ratio)}")
    return "; ".join(parts)
