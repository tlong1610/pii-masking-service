from datetime import datetime

from bson import Decimal128

from piimask.profile import FieldProfiler, infer_data_type


def _profiles(records, **options):
    profiler = FieldProfiler("t", **options)
    for record in records:
        profiler.add(record)
    return {profile.column_name: profile for profile in profiler.profiles()}


def test_every_field_is_listed_with_full_path():
    profiles = _profiles([{"a": 1}, {"b": {"c": {"d": "x"}}}, {"m": [{"n": "y"}, "z"]}, {"e": None}, {"f": []}])
    assert set(profiles) == {"a", "b.c.d", "m[].n", "m[].value", "e"}


def test_samples_spread_over_the_whole_source():
    records = [{"a": f"v{index}"} for index in range(10_000)]
    samples = _profiles(records, sample_size=50)["a"].samples
    numbers = sorted(int(sample[1:]) for sample in samples)
    assert len(numbers) == 50
    assert numbers[-1] > 8000 and numbers[len(numbers) // 2] > 2000


def test_rare_field_keeps_all_its_values_as_samples():
    records = [{"a": 1}] * 1000 + [{"hiem": "x"}, {"hiem": "y"}]
    assert _profiles(records)["hiem"].samples == ["x", "y"]


def test_sampling_is_reproducible():
    records = [{"a": index} for index in range(500)]
    assert _profiles(records)["a"].samples == _profiles(records)["a"].samples


def test_null_and_blank_are_not_samples():
    profile = _profiles([{"a": None}, {"a": "  "}, {"a": ""}])["a"]
    assert profile.samples == []
    assert profile.data_type == "string"


def test_data_type_comes_from_first_real_value():
    assert _profiles([{"a": None}, {"a": True}])["a"].data_type == "boolean"
    assert infer_data_type(3) == "integer"
    assert infer_data_type(3.5) == "float"
    assert infer_data_type(datetime(2026, 1, 1)) == "date"
    assert infer_data_type({}) == "object"
    assert infer_data_type(Decimal128("1.5")) == "string"
