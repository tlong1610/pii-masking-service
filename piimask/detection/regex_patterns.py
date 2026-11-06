import re

from piimask.detection.taxonomy import PIIType

# ==========================================
# CÁC TỪ KHÓA TÊN CỘT RÕ RÀNG (HIGH CONFIDENCE)
# Khớp theo NGUYÊN TỪ (xem match_column_keyword): "phone" khớp home_phone, KHÔNG khớp headphone_model.
# Thứ tự có ý nghĩa: loại cụ thể hơn đứng trước (ip_address trước address).
# ==========================================
HIGH_CONFIDENCE_COLUMNS = {
    PIIType.CCCD.value: [
        "cccd", "cmnd", "so_dinh_danh", "identity_card", "national_id", "citizen_id", "passport",
        "passport_no", "ho_chieu",
    ],
    PIIType.EMAIL.value: ["email", "mail_address"],
    PIIType.PHONE.value: ["phone", "telephone", "tel", "sdt", "so_dien_thoai", "dien_thoai", "mobile", "fax"],
    PIIType.TAX_CODE.value: ["tax_code", "mst", "ma_so_thue"],
    PIIType.DOB.value: ["date_of_birth", "birth_date", "birthday", "dob", "ngay_sinh", "sinh_nhat"],
    "PASSWORD": ["password", "passwd", "pwd", "passphrase", "mat_khau", "matkhau"],
    "TOKEN": [
        "token", "access_token", "refresh_token", "api_key", "apikey", "authorization", "secret", "client_secret",
        "private_key",
    ],
    "SESSION_ID": ["session", "session_id", "sessionid"],
    "GPS": ["gps", "latitude", "longitude", "lat", "lng", "toa_do"],
    # IP/MAC là định danh gián tiếp, không phải địa chỉ nhà: phải đứng trước ADDRESS.
    "IP_ADDRESS": ["ip_address", "ip", "mac_address"],
    PIIType.ADDRESS.value: ["address", "dia_chi", "street", "street_address"],
    # Thành phố / quận: định danh gián tiếp (L1) - được Giữ nguyên để phân tích, không cần ngoại lệ.
    "CITY": ["city", "district", "ward", "town", "quan_huyen", "phuong_xa"],
    # Dữ liệu nhạy cảm (NĐ 356/2025 Điều 4 khoản 1): tài chính, sinh trắc, sức khỏe.
    "CREDIT_CARD": [
        "credit_card", "card_number", "bank_account", "bank_account_no", "account_number", "so_tai_khoan",
    ],
    "BIOMETRIC_FILE": ["face_image", "fingerprint", "id_card_front", "id_card_back"],
    "PATIENT_ID": ["patient_id", "ma_benh_nhan", "bhyt", "health_insurance"],
}

# Các từ khóa tên cột chắc chắn KHÔNG PHẢI PII CÁ NHÂN (Negative Cases).
# Chỉ áp dụng SAU khi đã loại trừ PII (regex nội dung + HIGH_CONFIDENCE). Cột "*_id" chung chung
# được xử lý riêng bởi is_generic_id_column (national_id, patient_id... KHÔNG được coi là an toàn).
NEGATIVE_COLUMNS = {
    PIIType.TRACKING_CODE.value: ["tracking_number", "tracking_code", "order_id", "order_number", "shipment_id", "waybill", "bill_of_lading"],
    PIIType.MONEY_ALONE.value: ["amount", "total_price", "unit_price", "balance", "fee", "cost", "freight"],
    "NOT_PERSONAL_DATA": [
        "customer_id", "company_name", "ship_via", "doc_type", "postal_code", "contact_title", "order_date",
        # Địa danh cấp quốc gia / vùng / bang không định danh được một người.
        "region", "country", "nation", "state", "province", "territory",
    ]
}

# Từ trong tên cột "*_id" cho thấy đây là mã định danh CON NGƯỜI, không phải khóa kỹ thuật.
_PERSONAL_ID_WORDS = frozenset(
    {
        "national", "citizen", "identity", "cccd", "cmnd", "passport", "patient", "tax", "dinh", "danh",
        "chieu", "benh", "bhyt", "insurance", "license", "driver", "social", "ssn", "voter", "personal",
    }
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def name_tokens(column_name: str) -> list[str]:
    """'customers.homePhone' -> ['customers', 'home', 'phone']; 'date_of_birth' -> ['date', 'of', 'birth']."""
    spaced = _CAMEL_BOUNDARY.sub("_", column_name)
    return [token for token in _TOKEN_SPLIT.split(spaced.lower()) if token]


def _contains_phrase(tokens: list[str], phrase: list[str]) -> bool:
    size = len(phrase)
    return size > 0 and any(tokens[i : i + size] == phrase for i in range(len(tokens) - size + 1))


def match_column_keyword(column_name: str, keyword_dict: dict[str, list[str]]) -> str | None:
    """First type whose keyword appears as WHOLE words in the column name (never as a substring of a word)."""
    tokens = name_tokens(column_name)
    for pii_type, keywords in keyword_dict.items():
        if any(_contains_phrase(tokens, name_tokens(keyword)) for keyword in keywords):
            return pii_type
    return None


def is_generic_id_column(column_name: str) -> bool:
    """A technical '*_id' key (order_id, product_id), not a personal identifier (national_id, patient_id)."""
    tokens = name_tokens(column_name)
    return bool(tokens) and tokens[-1] == "id" and not (set(tokens) & _PERSONAL_ID_WORDS)


# ==========================================
# REGEX KIỂM TRA DỮ LIỆU MẪU (SAMPLES)
# Phải đảm bảo Strict (Chặt chẽ) để tránh False Positive.
# ==========================================
REGEX_PATTERNS = {
    # Đúng 12 số (CCCD) - Bỏ 9 số để chặt chẽ theo yêu cầu
    PIIType.CCCD.value: re.compile(r"^\d{12}$"),

    # Định dạng chuẩn email
    PIIType.EMAIL.value: re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"),

    # Số điện thoại VN: Bắt đầu 0, 84 hoặc +84, sau đó là 3,5,7,8,9 và đúng 8 số đằng sau
    PIIType.PHONE.value: re.compile(r"^(0|84|\+84)(3|5|7|8|9)\d{8}$"),

    # Ma so thue
    PIIType.TAX_CODE.value: re.compile(r"^\d{10}(-\d{3})?$"),

    "IP_ADDRESS": re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$"),
    "GPS": re.compile(r"^-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}$"),
    "TOKEN": re.compile(r"^(?:(?:[Bb]earer|[Bb]asic)\s+\S{8,}|eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*)$"),
}


# ==========================================
# CỘT TÊN "<thực thể>_name": thực thể đi kèm quyết định đây có phải tên NGƯỜI hay không.
# ==========================================
_NAME_WORDS = frozenset({"name", "names", "ten"})
# Thực thể là con người -> họ tên (L2).
_PERSON_NAME_ENTITIES = [
    "first", "last", "full", "middle", "given", "family", "sur", "contact", "customer", "client", "employee",
    "staff", "ship", "receiver", "recipient", "consignee", "sender", "patient", "student", "person", "owner",
    "guardian", "parent", "spouse", "ho", "nguoi_nhan", "khach_hang", "nhan_vien", "benh_nhan",
]
# Thực thể là vật / tổ chức / địa danh -> không phải dữ liệu cá nhân.
_NON_PERSON_NAME_ENTITIES = [
    "product", "category", "company", "brand", "supplier", "shipper", "vendor", "store", "shop", "branch",
    "department", "dept", "organization", "org", "bank", "project", "item", "model", "service", "plan", "course",
    "table", "column", "file", "host", "domain", "event", "campaign", "tag", "role", "team", "state", "region",
    "territory", "country", "province", "warehouse", "san_pham", "danh_muc", "cong_ty", "chi_nhanh",
    "thuong_hieu",
]


def classify_name_column(column_name: str) -> str | None:
    """'first_name' -> FULL_NAME, 'product_name' -> NOT_PERSONAL_DATA; bare/unclear names -> None."""
    tokens = name_tokens(column_name)
    if not set(tokens) & _NAME_WORDS:
        return None
    is_person = match_column_keyword(column_name, {"FULL_NAME": _PERSON_NAME_ENTITIES}) is not None
    is_thing = match_column_keyword(column_name, {"NOT_PERSONAL_DATA": _NON_PERSON_NAME_ENTITIES}) is not None
    if is_person and not is_thing:
        return "FULL_NAME"
    if is_thing and not is_person:
        return "NOT_PERSONAL_DATA"
    return None
