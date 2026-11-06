"""Sinh bộ file giả như file tải từ S3 về, kèm nhãn theo cột và theo dòng. Chỉ dùng khách cá nhân."""

import csv
import gzip
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from openpyxl import Workbook

from mockup.documents import build_text, make_ticket
from mockup.labels import field_labels
from mockup.values import FakeValues
from piimask.detection.taxonomy import legal_group

# Cột: (tên, loại PII, hành động). Loại None là không phải PII.
_CUSTOMER_COLUMNS = [
    ("ma_kh", "CUSTOMER_ID", "HMAC"),
    ("ho_ten", "FULL_NAME", "MASK"),
    ("sdt", "PHONE", "PARTIAL"),
    ("cccd", "CCCD", "MASK"),
    ("email", "EMAIL", "HMAC"),
    ("ngay_sinh", "DOB", "MASK"),
    ("dia_chi", "ADDRESS", "MASK"),
    ("c1", "PHONE", "PARTIAL"),
    ("so_tien", None, "KEEP"),
    ("ma_van_don", None, "KEEP"),
    ("ghi_chu", "FREE_TEXT", "REDACT"),
]
_PAYMENT_COLUMNS = [
    ("ma_gd", None, "KEEP"),
    ("chu_tk", "FULL_NAME", "MASK"),
    ("so_tk", "BANK_ACCOUNT", "MASK"),
    ("so_the", "CREDIT_CARD", "PARTIAL"),
    ("so_tien", None, "KEEP"),
    ("ngay_gd", None, "KEEP"),
]
_NESTED_JSON_PATHS = {
    "ma_kh": ("CUSTOMER_ID", "HMAC"),
    "thong_tin.ho_ten": ("FULL_NAME", "MASK"),
    "thong_tin.lien_he.sdt": ("PHONE", "PARTIAL"),
    "thong_tin.lien_he.email": ("EMAIL", "HMAC"),
    "thong_tin.giay_to.cccd": ("CCCD", "MASK"),
    "ngay_sinh": ("DOB", "MASK"),
    "dia_chi": ("ADDRESS", "MASK"),
    "ghi_chu": ("FREE_TEXT", "REDACT"),
    "hop_dong[].ma_hd": (None, "KEEP"),
    "hop_dong[].so_tien": (None, "KEEP"),
}
_PARQUET_COLUMNS = [
    ("ma_gd", None, "KEEP"),
    ("so_tk", "BANK_ACCOUNT", "MASK"),
    ("so_the", "CREDIT_CARD", "PARTIAL"),
    ("so_tien", None, "KEEP"),
    ("ngay_gd", None, "KEEP"),
    ("nguoi_tra.ho_ten", "FULL_NAME", "MASK"),
    ("nguoi_tra.sdt", "PHONE", "PARTIAL"),
]
_CSV_FORMATS = [
    ("csv/khach_hang_utf8.csv", ",", "utf-8"),
    ("csv/khach_hang_cham_phay.csv", ";", "utf-8-sig"),
]
_PAYMENT_CSV = ("csv/thanh_toan_tab_utf16.csv", "\t", "utf-16")
_XLSX = "excel/khach_hang.xlsx"
_NESTED_JSON = "json/khach_hang.json"
_PARQUET = "parquet/thanh_toan.parquet"
_LOG = "log/app.log"
_LOG_GZ = "log/app.log.gz"
_EVENTS = "log/events.jsonl"


_SECRET_LOG = "log/secrets.log"


def _customer_rows(v: FakeValues, customers: list[dict]) -> tuple[list[dict], list[list[dict]]]:
    rows, spans = [], []
    for index, customer in enumerate(customers):
        ticket, labels = make_ticket(v, customer, index)
        rows.append(
            {
                "ma_kh": customer["CustomerId"],
                "ho_ten": customer["FullName"],
                "sdt": customer["PhoneNumber"],
                "cccd": customer["IdNumber"],
                "email": customer["Email"],
                "ngay_sinh": customer["DateOfBirth"].replace(tzinfo=None),
                "dia_chi": customer["Address"],
                "c1": v.phone(),
                "so_tien": v.rng.randrange(500_000, 6_000_000, 1000),
                "ma_van_don": v.digits(12),
                "ghi_chu": ticket["Note"],
            }
        )
        spans.append(labels)
    return rows, spans


def _payment_rows(v: FakeValues, customers: list[dict]) -> list[dict]:
    return [
        {
            "ma_gd": v.digits(12),
            "chu_tk": customer["FullName"],
            "so_tk": v.bank_account(),
            "so_the": v.card_number() if v.rng.random() < 0.5 else None,
            "so_tien": v.rng.randrange(500_000, 6_000_000, 1000),
            "ngay_gd": v.date().replace(tzinfo=None),
            "sdt": customer["PhoneNumber"],
        }
        for customer in customers
    ]


def _write_csv(path: Path, rows: list[dict], columns: list[str], delimiter: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as file:
        writer = csv.writer(file, delimiter=delimiter, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(
                [row[name].strftime("%d/%m/%Y") if hasattr(row[name], "strftime") else row[name] for name in columns]
            )


def _write_xlsx(path: Path, customer_rows: list[dict], payment_rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    customers_sheet = book.active
    customers_sheet.title = "KhachHang"
    names = [name for name, _, _ in _CUSTOMER_COLUMNS]
    # Dòng 1 là tiêu đề gộp ô, dòng 2 là tên cột.
    customers_sheet.append(["Danh sách khách hàng"])
    customers_sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(names))
    customers_sheet.append(names)
    for row in customer_rows:
        customers_sheet.append([row[name] for name in names])

    payments_sheet = book.create_sheet("ThanhToan")
    names = [name for name, _, _ in _PAYMENT_COLUMNS]
    payments_sheet.append(names)
    for row in payment_rows:
        payments_sheet.append([row[name] for name in names])
    book.save(path)


def _write_nested_json(path: Path, v: FakeValues, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    documents = [
        {
            "ma_kh": row["ma_kh"],
            "thong_tin": {
                "ho_ten": row["ho_ten"],
                "lien_he": {"sdt": row["sdt"], "email": row["email"]},
                "giay_to": {"cccd": row["cccd"]},
            },
            "ngay_sinh": row["ngay_sinh"].strftime("%Y-%m-%d"),
            "dia_chi": row["dia_chi"],
            "ghi_chu": row["ghi_chu"],
            "hop_dong": [{"ma_hd": f"N{v.digits(5)}-25-{v.digits(4)}", "so_tien": row["so_tien"]}],
        }
        for row in rows
    ]
    path.write_text(json.dumps(documents, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payer = pa.struct([("ho_ten", pa.string()), ("sdt", pa.string())])
    table = pa.table(
        {
            "ma_gd": pa.array([row["ma_gd"] for row in rows], pa.string()),
            "so_tk": pa.array([row["so_tk"] for row in rows], pa.string()),
            "so_the": pa.array([row["so_the"] for row in rows], pa.string()),
            "so_tien": pa.array([Decimal(row["so_tien"]) for row in rows], pa.decimal128(18, 0)),
            "ngay_gd": pa.array([row["ngay_gd"] for row in rows], pa.timestamp("ms")),
            "nguoi_tra": pa.array([{"ho_ten": row["chu_tk"], "sdt": row["sdt"]} for row in rows], payer),
        }
    )
    pq.write_table(table, path)


def _json_line(payload: dict, entities: list[tuple[str, str]]) -> tuple[str, list[dict]]:
    line = json.dumps(payload, ensure_ascii=False)
    spans = []
    for pii_type, value in entities:
        start = line.index(value)
        spans.append({"type": pii_type, "start": start, "end": start + len(value)})
    return line, spans


def _log_line(v: FakeValues, customer: dict, index: int) -> tuple[str, list[dict]]:
    stamp = (v.date() + timedelta(seconds=index)).strftime("%Y-%m-%d %H:%M:%S")
    name = ("FULL_NAME", customer["FullName"])
    phone = ("PHONE", customer["PhoneNumber"])
    email = ("EMAIL", customer["Email"])
    ip = ("IP_ADDRESS", v.ip())
    session = ("SESSION_ID", v.session_id())
    token = ("TOKEN", v.token())
    password = ("PASSWORD", v.password())
    gps = ("GPS", v.gps())
    waybill = v.digits(12)
    templates = [
        [f"{stamp} INFO  [payment] Thanh toán thành công cho ", name, ", số điện thoại ", phone],
        [f"{stamp} WARN  [auth] Đăng nhập sai từ IP ", ip, ", session ", session],
        [f"{stamp} ERROR [otp] Gửi OTP tới ", email, " thất bại, token ", token],
        [f"{stamp} INFO  [geo] Xe ở tọa độ ", gps, ", mã vận đơn ", waybill],
        [f"{stamp} DEBUG [login] user=", email, " password=", password],
        [f"{stamp} INFO  [sync] Đồng bộ xong {v.rng.randint(1, 900)} bản ghi, mã vận đơn cuối ", waybill],
    ]
    if v.rng.random() < 0.2:
        payload = {
            "ts": stamp,
            "level": "INFO",
            "event": "kyc",
            "user": {"cccd": customer["IdNumber"], "phone": customer["PhoneNumber"]},
        }
        return _json_line(payload, [("CCCD", customer["IdNumber"]), phone])
    return build_text(v.rng.choice(templates))


def _write_logs(data_dir: Path, lines: list[str]) -> None:
    path = data_dir / _LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(f"{line}\n" for line in lines).encode("utf-8")
    path.write_bytes(content)
    # mtime cố định để cùng seed ra cùng file nén.
    with (data_dir / _LOG_GZ).open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as file:
        file.write(content)


def _event(v: FakeValues, customer: dict, index: int) -> dict:
    """Log object nhiều dạng sự kiện: PII ở trường lồng sâu, trong chuỗi JSON lồng và trong thông báo tự do."""
    base = {"event_id": f"EV-{index:06d}", "service": "battery-api", "level": "INFO"}
    shape = index % 3
    if shape == 0:
        return {
            **base,
            "event": "payment",
            "actor": {"user": {"email": customer["Email"], "full_name": customer["FullName"]}},
            "meta": {"ip": v.ip(), "session": v.session_id()},
            "amount": v.rng.randrange(500_000, 6_000_000, 1000),
        }
    if shape == 1:
        return {
            **base,
            "event": "profile_update",
            "payload": json.dumps({"phone": customer["PhoneNumber"], "cccd": customer["IdNumber"]}),
            "message": f"Cập nhật hồ sơ cho {customer['FullName']}, số {customer['PhoneNumber']}",
        }
    return {
        **base,
        "event": "api_call",
        "device": {"location": {"gps": v.gps()}},
        "context": {"request": {"headers": {"authorization": v.token()}}},
        "waybill_no": v.digits(12),
    }


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8")


def _column_labels(file: str, sheet: str | None, columns: list[tuple]) -> list[dict]:
    return [
        {"file": file, "sheet": sheet, "column": name, "pii_type": pii, "group": legal_group(pii), "action": action}
        for name, pii, action in columns
    ]


def _cell_spans(file: str, sheet: str | None, column: str, spans: list[list[dict]]) -> list[dict]:
    """row đếm từ 0 trên các dòng dữ liệu, không tính dòng tiêu đề."""
    return [
        {"file": file, "sheet": sheet, "column": column, "row": row, "labels": labels}
        for row, labels in enumerate(spans)
    ]


def _jwt(v: FakeValues) -> str:
    """Hình dạng JWT, ba phần base64url, không phải token thật."""
    return f"eyJhbGciOiJIUzI1NiJ9.eyJ{v.hex_upper(24).lower()}.{v.hex_upper(32).lower()}"


def _secret_line(v: FakeValues, index: int) -> tuple[str, list[dict]]:
    """Dòng log có bí mật ở nhiều định dạng, xen dòng trông giống nhưng không chứa bí mật."""
    stamp = (v.date() + timedelta(seconds=index)).strftime("%Y-%m-%dT%H:%M:%SZ")
    api_key = ("TOKEN", f"key_{v.hex_upper(32).lower()}")
    password = ("PASSWORD", v.password())
    session = ("SESSION_ID", v.hex_upper(32))
    ip = ("IP_ADDRESS", v.ip())
    latitude = ("GPS", f"{v.rng.uniform(8.5, 23.0):.5f}")
    longitude = ("GPS", f"{v.rng.uniform(102.0, 109.5):.5f}")
    templates = [
        [f"{stamp} INFO gateway Authorization: Bearer ", ("TOKEN", _jwt(v))],
        [f"{stamp} DEBUG http header x-api-key: ", api_key],
        [f"{stamp} INFO http GET /v1/devices?api_key=", api_key, "&page=2"],
        [f"{stamp} WARN auth client_secret=", ("TOKEN", v.hex_upper(40).lower()), " bị từ chối"],
        [f'{stamp} DEBUG config {{"user":"svc","password":"', password, '","retries":3}'],
        [f"{stamp} INFO portal đổi mật khẩu: ", password],
        [f"{stamp} DEBUG db pwd=", password, " host=db-demo"],
        [f"{stamp} INFO web Cookie: JSESSIONID=", session, "; lang=vi"],
        [f"{stamp} INFO web session_id=", session, " user=svc"],
        [f"{stamp} INFO nginx src=", ip, " dst=", ("IP_ADDRESS", v.ip()), " status=200"],
        [f"{stamp} INFO tracker lat=", latitude, " lng=", longitude, " speed=42"],
        [f"{stamp} INFO app token hết hạn, yêu cầu đăng nhập lại"],
        [f"{stamp} INFO app session expired after 1800 seconds"],
        [f"{stamp} INFO app password changed successfully"],
        [f"{stamp} INFO app đổi mật khẩu thành công"],
        [f"{stamp} INFO deploy phiên bản v2.14.3.7 khởi động, timeout=30 retries=3"],
        [f"{stamp} INFO billing tổng 1.250.000 đồng, tỷ lệ 0.0825"],
    ]
    return build_text(v.rng.choice(templates))


def write_secret_log(data_dir: Path, v: FakeValues, log_lines: int) -> list[dict]:
    """File log riêng để không làm đổi các log đã có baseline. Trả nhãn vị trí."""
    lines, position_labels = [], []
    for index in range(log_lines):
        line, labels = _secret_line(v, index)
        lines.append(line)
        position_labels.append({"file": _SECRET_LOG, "line": index + 1, "labels": labels})
    (data_dir / _SECRET_LOG).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return position_labels


def write_files(data_dir: Path, v: FakeValues, customers: list[dict], rows: int, log_lines: int) -> tuple[list, list]:
    """Ghi bộ file vào data_dir, trả nhãn theo cột và nhãn vị trí."""
    individuals = [customer for customer in customers if not customer["EnterpriseCustomer"]][:rows]
    customer_rows, spans = _customer_rows(v, individuals)
    payment_rows = _payment_rows(v, individuals)

    column_labels: list[dict] = []
    position_labels: list[dict] = []

    customer_names = [name for name, _, _ in _CUSTOMER_COLUMNS]
    for file, delimiter, encoding in _CSV_FORMATS:
        _write_csv(data_dir / file, customer_rows, customer_names, delimiter, encoding)
        column_labels += _column_labels(file, None, _CUSTOMER_COLUMNS)
        position_labels += _cell_spans(file, None, "ghi_chu", spans)

    file, delimiter, encoding = _PAYMENT_CSV
    _write_csv(data_dir / file, payment_rows, [name for name, _, _ in _PAYMENT_COLUMNS], delimiter, encoding)
    column_labels += _column_labels(file, None, _PAYMENT_COLUMNS)

    _write_xlsx(data_dir / _XLSX, customer_rows, payment_rows)
    column_labels += _column_labels(_XLSX, "KhachHang", _CUSTOMER_COLUMNS)
    column_labels += _column_labels(_XLSX, "ThanhToan", _PAYMENT_COLUMNS)
    position_labels += _cell_spans(_XLSX, "KhachHang", "ghi_chu", spans)

    _write_nested_json(data_dir / _NESTED_JSON, v, customer_rows)
    nested = [(path, pii, action) for path, (pii, action) in _NESTED_JSON_PATHS.items()]
    column_labels += _column_labels(_NESTED_JSON, None, nested)
    position_labels += _cell_spans(_NESTED_JSON, None, "ghi_chu", spans)

    _write_parquet(data_dir / _PARQUET, payment_rows)
    column_labels += _column_labels(_PARQUET, None, _PARQUET_COLUMNS)

    lines, line_spans = [], []
    for index in range(log_lines):
        line, labels = _log_line(v, v.rng.choice(individuals), index)
        lines.append(line)
        line_spans.append(labels)
    _write_logs(data_dir, lines)
    for file in (_LOG, _LOG_GZ):
        position_labels += [
            {"file": file, "line": number, "labels": labels} for number, labels in enumerate(line_spans, start=1)
        ]

    events = [_event(v, v.rng.choice(individuals), index) for index in range(log_lines)]
    _write_events(data_dir / _EVENTS, events)
    for label in field_labels("app_events", events):
        column_labels.append(
            {
                "file": _EVENTS,
                "sheet": None,
                "column": label["path"],
                "pii_type": label["pii_type"],
                "group": label["group"],
                "action": label["action"],
            }
        )

    return column_labels, position_labels
