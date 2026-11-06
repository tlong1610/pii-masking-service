import csv
import gzip
import json

import pytest

from mockup.generate import write_mockup
from tool.mask_file import detect_encoding, mask_csv, mask_file, mask_log

SIZES = {"customers": 120, "battery_bills": 20, "tickets": 20, "devices": 5, "file_rows": 120, "log_lines": 200}
KEYS = {"secret": "s", "key_version": "v1"}


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    root = tmp_path_factory.mktemp("mockup")
    write_mockup(root / "data", root / "labels", seed=5, sizes=SIZES)
    return root / "data" / "files"


def _read(path, delimiter, encoding):
    with path.open(encoding=encoding, newline="") as file:
        return list(csv.reader(file, delimiter=delimiter))


@pytest.mark.parametrize(
    ("name", "delimiter", "encoding"),
    [
        ("csv/khach_hang_utf8.csv", ",", "utf-8"),
        ("csv/khach_hang_cham_phay.csv", ";", "utf-8-sig"),
        ("csv/thanh_toan_tab_utf16.csv", "\t", "utf-16"),
    ],
)
def test_csv_keeps_encoding_delimiter_columns_and_row_count(files, tmp_path, name, delimiter, encoding):
    target = tmp_path / "out.csv"
    mask_csv(files / name, target, **KEYS)
    before, after = _read(files / name, delimiter, encoding), _read(target, delimiter, encoding)
    assert detect_encoding(target) == detect_encoding(files / name)
    assert after[0] == before[0]
    assert len(after) == len(before)
    assert {len(row) for row in after} == {len(before[0])}
    assert after != before


def test_csv_masks_detected_and_undecided_columns_and_keeps_money(tmp_path):
    source = tmp_path / "in.csv"
    source.write_text("so_dien_thoai,cot_la,amount\n0912345678,abc,150000\n", encoding="utf-8")
    decisions = mask_csv(source, tmp_path / "out.csv", **KEYS)
    assert (tmp_path / "out.csv").read_text(encoding="utf-8") == "so_dien_thoai,cot_la,amount\n091***678,***,150000\n"
    assert decisions[0].pii_type == "PHONE"


def test_csv_keeps_windows_line_endings_and_masks_cells_beyond_header(tmp_path):
    source = tmp_path / "in.csv"
    source.write_bytes(b"amount\r\n100,0912345678\r\n")
    mask_csv(source, tmp_path / "out.csv", **KEYS)
    assert (tmp_path / "out.csv").read_bytes() == b"amount\r\n100,***\r\n"


def test_log_keeps_line_count_and_json_lines_stay_valid(files, tmp_path):
    source, target = files / "log/app.log", tmp_path / "app.log"
    mask_log(source, target, **KEYS)
    before = source.read_text(encoding="utf-8").splitlines()
    after = target.read_text(encoding="utf-8").splitlines()
    assert len(after) == len(before) == SIZES["log_lines"]
    assert after != before
    json_lines = [line for line in after if line.startswith("{")]
    assert json_lines
    for line in json_lines:
        json.loads(line)


def test_gz_is_compressed_again_with_same_lines_as_plain_log(files, tmp_path):
    mask_log(files / "log/app.log", tmp_path / "app.log", **KEYS)
    mask_log(files / "log/app.log.gz", tmp_path / "app.log.gz", **KEYS)
    assert (tmp_path / "app.log.gz").read_bytes()[:2] == b"\x1f\x8b"
    assert gzip.decompress((tmp_path / "app.log.gz").read_bytes()) == (tmp_path / "app.log").read_bytes()


def test_log_keeps_bytes_that_are_not_utf8_and_masks_the_rest(tmp_path):
    source = tmp_path / "in.log"
    source.write_bytes(b"a\xff 0912345678\r\nb\n")
    mask_log(source, tmp_path / "out.log", **KEYS)
    assert (tmp_path / "out.log").read_bytes() == b"a\xff [PHONE]\r\nb\n"


def test_log_line_that_cannot_be_masked_is_withheld_and_line_count_stays(tmp_path, monkeypatch):
    def boom(text):
        raise RuntimeError("lỗi")

    monkeypatch.setattr("piimask.transform.mask_engine.mask_text", boom)
    source = tmp_path / "in.log"
    source.write_text("gọi 0912345678\nb\n", encoding="utf-8")
    mask_log(source, tmp_path / "out.log", **KEYS)
    assert (tmp_path / "out.log").read_text(encoding="utf-8") == "[REDACTED]\n[REDACTED]\n"


def test_failure_leaves_no_partial_output(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("lỗi")

    monkeypatch.setattr("tool.mask_file._mask_line", boom)
    source = tmp_path / "in.log"
    source.write_text("x\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        mask_log(source, tmp_path / "out.log", **KEYS)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["in.log"]


def test_refuses_same_file_and_unknown_format(tmp_path):
    source = tmp_path / "in.csv"
    source.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="khác"):
        mask_file(source, source, **KEYS)
    with pytest.raises(ValueError, match="parquet"):
        mask_file(tmp_path / "a.parquet", tmp_path / "b.parquet", **KEYS)


def test_csv_kept_column_goes_through_last_guard(tmp_path):
    source = tmp_path / "in.csv"
    source.write_text("amount\n100\n200\n300\ngọi 0912345678\n", encoding="utf-8")
    mask_csv(source, tmp_path / "out.csv", **KEYS)
    assert (tmp_path / "out.csv").read_text(encoding="utf-8") == "amount\n100\n200\n300\ngọi [PHONE]\n"


def test_csv_samples_cover_rows_after_the_first_hundred(tmp_path):
    source = tmp_path / "in.csv"
    rows = "".join(f"{'' if index < 500 else '0912345678'}\n" for index in range(600))
    source.write_text(f"cot_la\n{rows}", encoding="utf-8")
    decisions = mask_csv(source, tmp_path / "out.csv", **KEYS)
    assert decisions[0].pii_type == "PHONE"
