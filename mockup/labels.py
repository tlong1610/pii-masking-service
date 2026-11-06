"""Nhãn chuẩn theo trường. Trường không khai báo ở đây được ghi nhãn không phải PII, hành động KEEP.

Căn cứ: Luật Bảo vệ dữ liệu cá nhân 2025 và Nghị định 356/2025/NĐ-CP. Luật chỉ bảo vệ con người cụ thể,
nên trường gắn với khách doanh nghiệp không phải dữ liệu cá nhân (nhãn có khóa when).
Mã khách hàng là cơ bản theo Điều 3 k11 vì nối được tới một người.
CCCD mặc định MASK, là khóa nối thì HMAC. HMAC không phải khử nhận dạng: người giữ khóa vẫn nối lại được.
decision=theo_ngu_canh: suy luận từ Điều 3 k11, luật không nêu đích danh, mentor có thể quyết khác.
"""

from piimask.detection.taxonomy import legal_group

_INDIVIDUAL = {"field": "EnterpriseCustomer", "equals": False}


def _pii(pii_type: str, action: str, **extra) -> dict:
    return {"pii_type": pii_type, "action": action, **extra}


def _individual(pii_type: str, action: str, **extra) -> dict:
    """Chỉ che khi khách là cá nhân; khách doanh nghiệp thì giữ nguyên."""
    return _pii(pii_type, action, when=_INDIVIDUAL, **extra)


_PERSON = {
    "CustomerId": _individual("CUSTOMER_ID", "HMAC"),
    "SapCustomerId": _individual("CUSTOMER_ID", "HMAC"),
    "FullName": _pii("FULL_NAME", "MASK"),
    "Email": _pii("EMAIL", "HMAC"),
    "PhoneNumber": _pii("PHONE", "PARTIAL"),
    "Address": _pii("ADDRESS", "MASK"),
    "TaxRegistrationNumber": _individual("TAX_CODE", "MASK"),
}

_AUDIT = {"CreatedBy": _pii("EMAIL", "HMAC"), "ModifiedBy": _pii("EMAIL", "HMAC")}

# Số khung gắn với khách cá nhân là dữ liệu cá nhân. Serial pin trùng số khung nên che theo.
_VIN = _individual("VIN", "HMAC", decision="theo_ngu_canh")

PII_FIELDS: dict[str, dict[str, dict]] = {
    "customers": {
        **_PERSON,
        "IdNumber": _pii("CCCD", "HMAC"),
        "DateOfBirth": _pii("DOB", "MASK"),
        "TaxRegistrationName": _individual("FULL_NAME", "MASK"),
        "c1": _pii("CCCD", "MASK"),
        "c2": _pii("PHONE", "PARTIAL"),
    },
    "battery_contracts": {
        **_PERSON,
        **_AUDIT,
        "IdNumber": _pii("CCCD", "HMAC"),
        "TaxRegistrationName": _individual("FULL_NAME", "MASK"),
        "VehicleId": _VIN,
        "Batteries[].Serial": _VIN,
        "Batteries[].Stock": _VIN,
    },
    "battery_bills": {
        **_PERSON,
        **_AUDIT,
        "IDNumber": _pii("CCCD", "HMAC"),
        "VehicleId": _VIN,
        "BatterySerial": _VIN,
        "CardNumber": _pii("CREDIT_CARD", "PARTIAL"),
        "PaidAt.AccountNumber": _pii("BANK_ACCOUNT", "MASK"),
    },
    # Ticket không có trường phân biệt loại khách nên luôn che mã khách.
    "tickets": {
        "CustomerId": _pii("CUSTOMER_ID", "HMAC"),
        "Note": _pii("FREE_TEXT", "REDACT"),
        "AssignedTo": _pii("EMAIL", "HMAC"),
    },
    # Thiết bị không gắn với khách: Serial, Imei không phải dữ liệu cá nhân, giữ làm hard negative.
    "devices": {},
    # Log object trong log/events.jsonl. payload là chuỗi JSON lồng.
    "app_events": {
        "actor.user.email": _pii("EMAIL", "HMAC"),
        "actor.user.full_name": _pii("FULL_NAME", "MASK"),
        "meta.ip": _pii("IP_ADDRESS", "HMAC"),
        "meta.session": _pii("SESSION_ID", "HMAC"),
        "payload": _pii("FREE_TEXT", "REDACT"),
        "message": _pii("FREE_TEXT", "REDACT"),
        "device.location.gps": _pii("GPS", "MASK"),
        "context.request.headers.authorization": _pii("TOKEN", "MASK"),
    },
}


def field_paths(doc: dict, prefix: str = ""):
    """Đường dẫn lá của document: 'PaidAt.AccountNumber', 'Batteries[].Serial', 'PaymentMethodHistory[]'."""
    for key, value in doc.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            yield from field_paths(value, f"{path}.")
        elif isinstance(value, list) and value:
            for item in value:
                if isinstance(item, dict):
                    yield from field_paths(item, f"{path}[].")
                else:
                    yield f"{path}[]"
        else:
            yield path


def field_labels(collection: str, docs: list[dict]) -> list[dict]:
    """Một nhãn cho mỗi đường dẫn có trong collection, sắp theo đường dẫn."""
    paths = sorted({path for doc in docs for path in field_paths(doc)})
    labels = []
    for path in paths:
        label = PII_FIELDS[collection].get(path, {"pii_type": None, "action": "KEEP"})
        labels.append({"collection": collection, "path": path, "group": legal_group(label["pii_type"]), **label})
    return labels


def catalog(collection: str, labels: list[dict]) -> dict:
    """Danh mục trường PII chuẩn của một collection. Không chứa giá trị."""
    fields = [
        {key: value for key, value in label.items() if key != "collection"}
        for label in labels
        if label["pii_type"] is not None
    ]
    return {"schemaVersion": 1, "engine": "mongodb", "collection": collection, "fields": fields}
