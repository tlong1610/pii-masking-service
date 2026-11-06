"""Bí mật trong dòng log: chỉ che phần giá trị, không che dòng chỉ nhắc tới từ khóa."""

import pytest

from piimask.detection.regex_ner import RegexNERScanner


def _found(text):
    return [(match.pii_type, match.text) for match in RegexNERScanner().scan_text(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password=Abc123!", ("PASSWORD", "Abc123!")),
        ("PWD: hunter2", ("PASSWORD", "hunter2")),
        ('{"user":"svc","password":"a b,c"}', ("PASSWORD", "a b,c")),
        ("mat_khau='Xy12'", ("PASSWORD", "Xy12")),
        ("đổi mật khẩu: Demo99!", ("PASSWORD", "Demo99!")),
        ("api_key=abcd1234&page=2", ("TOKEN", "abcd1234")),
        ("x-api-key: abcd1234", ("TOKEN", "abcd1234")),
        ("client_secret=deadbeef thất bại", ("TOKEN", "deadbeef")),
        ("Authorization: Bearer abc.def-123", ("TOKEN", "abc.def-123")),
        ("authorization: basic dXNlcjpwYXNz", ("TOKEN", "dXNlcjpwYXNz")),
        ("thất bại, token tok_abc123def", ("TOKEN", "tok_abc123def")),
        ("jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIx.c2lnbmF0dXJl", ("TOKEN", "eyJhbGciOiJIUzI1.eyJzdWIiOiIx.c2lnbmF0dXJl")),
        ("Cookie: JSESSIONID=ABCDEF0123; lang=vi", ("SESSION_ID", "ABCDEF0123")),
        ("session_id=abc123 user=a", ("SESSION_ID", "abc123")),
        ("sai từ IP 10.1.2.3, session sess_ab12cd34", ("SESSION_ID", "sess_ab12cd34")),
        ("src=192.168.1.10 status=200", ("IP_ADDRESS", "192.168.1.10")),
        ("từ 2001:db8:0:0:0:0:0:1 tới", ("IP_ADDRESS", "2001:db8:0:0:0:0:0:1")),
        ("từ fe80::1 tới", ("IP_ADDRESS", "fe80::1")),
        ("Xe ở tọa độ 21.02851,105.85421, dừng", ("GPS", "21.02851,105.85421")),
        ("lat=21.0285 lng=105.8542", ("GPS", "21.0285")),
    ],
)
def test_value_is_found_and_key_is_kept(text, expected):
    assert expected in _found(text)


@pytest.mark.parametrize(
    "text",
    [
        "token hết hạn, yêu cầu đăng nhập lại",
        "session expired after 1800 seconds",
        "password changed successfully",
        "đổi mật khẩu thành công",
        "phiên bản v2.14.3.7 khởi động",
        "version 1.2.3.4.5 build",
        "timeout=30 retries=3 lúc 10:15:30",
        "tổng 1.250.000 đồng, tỷ lệ 0.0825",
        "999.1.1.1 không phải IP",
        "bộ lọc token.count và session.size",
    ],
)
def test_lines_without_secret_are_left_alone(text):
    assert _found(text) == []


def test_secret_wins_over_number_patterns():
    assert _found("password=0912345678") == [("PASSWORD", "0912345678")]


def test_nothing_after_key_is_not_an_entity():
    assert _found("password= ") == []
