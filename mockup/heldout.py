"""Đổi tên trường để đo bộ quét trên tên chưa từng dùng khi viết detector.

Giá trị và nhãn giữ nguyên, chỉ đổi tên. Bộ held-out trộn năm kiểu đặt tên; chế độ ngẫu nhiên thay mọi tên bằng chuỗi vô
nghĩa nên chỉ còn nội dung để phát hiện. Không thêm tên trong bảng này vào từ khóa của detector: làm vậy thì số đo trên
bộ này không còn nói lên điều gì.
"""

import hashlib
import random
import re
from collections.abc import Iterable
from typing import Any

STYLES = ("camelCase", "snake_case", "khong_dau", "viet_tat", "vo_nghia")

# Tên gốc -> một tên cho mỗi kiểu, theo thứ tự của STYLES.
_NAMES = {
    "FullName": ("customerFullName", "ten_khach", "hoten", "kh_nm", "a1"),
    "TaxRegistrationName": ("invoiceHolder", "invoice_name", "ten_hoa_don", "tenhd", "j0"),
    "Email": ("contactMail", "e_mail_addr", "thu_dien_tu", "eml", "b2"),
    "CreatedBy": ("creatorMail", "author_mail", "nguoi_tao", "ngt", "o5"),
    "ModifiedBy": ("editorMail", "last_editor", "nguoi_sua", "ngs", "o6"),
    "AssignedTo": ("handlerMail", "assignee", "nguoi_xu_ly", "nxl", "o7"),
    "PhoneNumber": ("mobileNo", "contact_no", "sdt", "dt", "c30"),
    "c2": ("altContact", "backup_no", "so_phu", "dtp", "c31"),
    "IdNumber": ("nationalIdNo", "citizen_no", "so_cmt", "cmt", "d4"),
    "IDNumber": ("nationalIdNo", "citizen_no", "so_cmt", "cmt", "d4"),
    "c1": ("legalIdentifier", "person_doc_no", "giay_to", "gt", "d5"),
    "Address": ("homeAddr", "permanent_addr", "noi_o", "dc", "e5"),
    "DateOfBirth": ("birthDay", "born_on", "ngay_sinh", "ns", "f6"),
    "CustomerId": ("custRef", "cust_code", "ma_kh", "mkh", "g7"),
    "SapCustomerId": ("sapCustRef", "sap_cust_no", "ma_sap", "sapkh", "h8"),
    "TaxRegistrationNumber": ("taxNo", "vat_no", "mst", "mstkh", "i9"),
    "VehicleId": ("vehicleVin", "chassis_no", "so_khung", "sk", "k1"),
    "BatterySerial": ("packSerial", "battery_sn", "so_seri_pin", "sn", "l2"),
    "Serial": ("serialNo", "serial_code", "so_seri", "sr", "l3"),
    "Stock": ("stockRef", "stock_code", "ma_kho", "mk", "l4"),
    "CardNumber": ("payCard", "pan_no", "so_the", "st", "m3"),
    "AccountNumber": ("bankAcct", "acct_no", "so_tk", "stk", "n4"),
    "Note": ("remarkText", "free_note", "ghi_chu", "gc", "p6"),
    # Hard negative: mã nghiệp vụ trùng định dạng PII.
    "WaybillNo": ("shipRef", "waybill_code", "ma_van_don", "mvd", "q1"),
    "Imei": ("deviceImei", "imei_code", "so_imei", "im", "q2"),
    "ContractNo": ("contractRef", "contract_code", "so_hop_dong", "shd", "q3"),
    "TransactionId": ("txnRef", "txn_no", "ma_giao_dich", "mgd", "q4"),
}

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _digest(*parts: str) -> str:
    return hashlib.sha1("/".join(parts).encode()).hexdigest()


def style_of(collection: str, name: str) -> str:
    return STYLES[int(_digest(collection, name), 16) % len(STYLES)]


def _generic_name(collection: str, name: str, style: str) -> str:
    words = _CAMEL_BOUNDARY.sub("_", name).lower().split("_")
    if style == "camelCase":
        return name[0].lower() + name[1:]
    if style == "viet_tat":
        return "".join(word[0] for word in words if word) + _digest(collection, name)[:2]
    if style == "vo_nghia":
        return f"v{_digest(collection, name)[:5]}"
    return "_".join(words)


def segments_of(paths: Iterable[str]) -> list[str]:
    """Tên từng cấp trong các đường dẫn, không kể ký hiệu mảng. _id giữ nguyên."""
    found = {segment.removesuffix("[]") for path in paths for segment in path.split(".")}
    return sorted(found - {"_id"})


def heldout_names(collection: str, segments: list[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for segment in segments:
        style = style_of(collection, segment)
        if segment in _NAMES:
            name = _NAMES[segment][STYLES.index(style)]
        else:
            name = _generic_name(collection, segment, style)
        # Hai tên gốc không được gộp thành một cột.
        while name in names.values():
            name += "_x"
        names[segment] = name
    return names


def random_names(collection: str, segments: list[str], seed: int) -> dict[str, str]:
    rng = random.Random(f"{collection}/{seed}")
    return {segment: f"f{rng.getrandbits(32):08x}" for segment in segments}


def rename_document(value: Any, names: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {names.get(key, key): rename_document(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [rename_document(item, names) for item in value]
    return value


def rename_path(path: str, names: dict[str, str]) -> str:
    parts = []
    for segment in path.split("."):
        plain = segment.removesuffix("[]")
        parts.append(names.get(plain, plain) + segment[len(plain) :])
    return ".".join(parts)
