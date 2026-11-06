import pytest

from piimask.detection.rule_engine import RuleBasedScanner
from piimask.detection.taxonomy import PIIType
from piimask.schemas import ColumnProfile


@pytest.fixture
def scanner():
    return RuleBasedScanner(match_threshold=0.5)


@pytest.fixture
def scanner_default():
    return RuleBasedScanner()


def test_tracking_code_not_cccd(scanner):
    # Tracking code giống CCCD (12 số) không được tính là CCCD
    profile = ColumnProfile(
        column_name="tracking_code",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["400691172582", "123456789012"],
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.TRACKING_CODE.value


def test_order_id_not_pii(scanner):
    # order id không phải PII
    profile = ColumnProfile(
        column_name="order_id",
        data_type="string",
        is_primary_key=True,
        is_foreign_key=False,
        samples=["ORD123", "ORD456"],
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.TRACKING_CODE.value


def test_org_email_detected_as_email(scanner):
    # email tổ chức
    profile = ColumnProfile(
        column_name="contact_email",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["support@company.vn", "contact@exoticliquids.co.uk"],
    )
    result = scanner.classify(profile)
    # Rule engine bắt bằng regex email nên sẽ ra EMAIL.
    assert result.inferred_pii_type == PIIType.EMAIL.value


def test_money_alone_non_personal(scanner):
    # số tiền đứng riêng non_personal
    profile = ColumnProfile(
        column_name="total_amount",
        data_type="float",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["1000.50", "200.0"],
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.MONEY_ALONE.value


def test_cccd_regex_strict_12_digits(scanner):
    # Đảm bảo CCCD phải đúng 12 số
    profile_9_digits = ColumnProfile(
        column_name="unknown_col",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["123456789"],  # CMND cũ 9 số
    )
    result = scanner.classify(profile_9_digits)
    # Không còn khớp CCCD vì regex đã siết chặt lại thành 12 số
    assert result is None

    profile_12_digits = ColumnProfile(
        column_name="unknown_col",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["033254456184"],
    )
    result_12 = scanner.classify(profile_12_digits)
    assert result_12.inferred_pii_type == PIIType.CCCD.value


def test_tax_code(scanner):
    profile = ColumnProfile(
        column_name="tax_number",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["8023456789"],
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.TAX_CODE.value


def _profile(name: str, samples: list[str], table: str | None = None) -> ColumnProfile:
    return ColumnProfile(
        table_name=table,
        column_name=name,
        data_type="character varying",
        is_primary_key=False,
        is_foreign_key=False,
        samples=samples,
    )


@pytest.mark.parametrize(
    ("name", "samples"),
    [
        ("national_id", ["001203004567", "079199001234"]),
        ("citizen_id", ["001203004567", "079199001234"]),
        ("ref_id", ["001203004567", "079199001234"]),
    ],
)
def test_personal_ids_holding_cccd_are_never_safe(scanner, name, samples):
    """Regression: '_id' substring used to mark these NOT_PERSONAL_DATA / KEEP (raw CCCD leak)."""
    result = scanner.classify(_profile(name, samples))
    assert result is not None
    assert result.inferred_pii_type == PIIType.CCCD.value


def test_personal_id_names_are_not_treated_as_technical_keys(scanner):
    result = scanner.classify(_profile("patient_id", ["BN-0001", "BN-0002"]))
    assert result is not None
    assert result.inferred_pii_type == "PATIENT_ID"


def test_generic_technical_id_is_non_personal(scanner):
    result = scanner.classify(_profile("product_id", ["17", "42"]))
    assert result is not None
    assert result.inferred_pii_type == "NOT_PERSONAL_DATA"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("headphone_model", None),
        ("ip_address", "IP_ADDRESS"),
        ("home_phone", PIIType.PHONE.value),
        ("homePhone", PIIType.PHONE.value),
        ("date_of_birth", PIIType.DOB.value),
    ],
)
def test_name_keywords_match_whole_words_only(scanner, name, expected):
    result = scanner.classify(_profile(name, ["sample text"]))
    assert (result.inferred_pii_type if result else None) == expected


def test_table_scoped_rules_apply_when_table_is_known(scanner):
    supplier_tax = scanner.classify(_profile("tax_code", ["0101234567"], table="suppliers"))
    assert supplier_tax.inferred_pii_type == "TAX_CODE_ORG"


def _typed(name: str, data_type: str, samples: list[str]) -> ColumnProfile:
    return ColumnProfile(
        column_name=name, data_type=data_type, is_primary_key=False, is_foreign_key=False, samples=samples
    )


@pytest.mark.parametrize(
    ("name", "data_type", "samples"),
    [
        ("hire_date", "date", ["1992-05-01"]),
        ("shipped_date", "timestamp without time zone", ["1996-07-16 00:00:00"]),
        ("created_at", "character varying", ["2024-01-02T10:00:00", "2024-02-03 11:30"]),
    ],
)
def test_event_dates_are_not_birth_dates(scanner, name, data_type, samples):
    result = scanner.classify(_typed(name, data_type, samples))
    assert result.inferred_pii_type == "NOT_PERSONAL_DATA"


def test_birth_date_is_still_dob(scanner):
    result = scanner.classify(_typed("birth_date", "date", ["1980-01-01"]))
    assert result.inferred_pii_type == PIIType.DOB.value


def test_empty_column_is_marked_empty(scanner):
    result = scanner.classify(_typed("customer_desc", "text", []))
    assert result.inferred_pii_type == "EMPTY_COLUMN"


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("ship_country", "NOT_PERSONAL_DATA"),
        ("state_name", "NOT_PERSONAL_DATA"),
        ("territory_description", "NOT_PERSONAL_DATA"),
        ("ship_city", "CITY"),
    ],
)
def test_geography_levels(scanner, name, expected_type):
    result = scanner.classify(_typed(name, "character varying", ["Hà Nội", "Lyon"]))
    assert result.inferred_pii_type == expected_type


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("first_name", "FULL_NAME"),
        ("last_name", "FULL_NAME"),
        ("contact_name", "FULL_NAME"),
        ("ship_name", "FULL_NAME"),
        ("ho_ten", "FULL_NAME"),
        ("product_name", "NOT_PERSONAL_DATA"),
        ("category_name", "NOT_PERSONAL_DATA"),
        ("shipper_name", "NOT_PERSONAL_DATA"),
        ("ten_san_pham", "NOT_PERSONAL_DATA"),
    ],
)
def test_name_columns_are_classified_by_their_entity(scanner, name, expected_type):
    result = scanner.classify(_typed(name, "character varying", ["Alpha Beta"]))
    assert result.inferred_pii_type == expected_type


@pytest.mark.parametrize("name", ["name", "display_name", "user_name"])
def test_unclear_name_columns_stay_undecided(scanner, name):
    assert scanner.classify(_typed(name, "character varying", ["Alpha Beta"])) is None


@pytest.mark.parametrize(
    ("name", "expected_type"),
    [
        ("password", "PASSWORD"),
        ("user_pwd", "PASSWORD"),
        ("mat_khau", "PASSWORD"),
        ("headers_authorization", "TOKEN"),
        ("api_key", "TOKEN"),
        ("access_token", "TOKEN"),
        ("meta_session", "SESSION_ID"),
        ("session_id", "SESSION_ID"),
        ("location_gps", "GPS"),
        ("latitude", "GPS"),
    ],
)
def test_secret_columns_by_name(scanner, name, expected_type):
    assert scanner.classify(_typed(name, "string", ["abc"])).inferred_pii_type == expected_type


@pytest.mark.parametrize(
    ("samples", "expected_type"),
    [
        (["10.1.2.3", "192.168.0.9"], "IP_ADDRESS"),
        (["21.02851,105.85421", "10.76260,106.66017"], "GPS"),
        (["Bearer abcdefgh12345"], "TOKEN"),
    ],
)
def test_secret_columns_by_content_under_meaningless_name(scanner, samples, expected_type):
    assert scanner.classify(_typed("f17", "string", samples)).inferred_pii_type == expected_type


def test_mixed_column_of_emails_and_system_codes_is_email(scanner_default):
    samples = ["a.b@example.com"] * 3 + ["SYSTEM"] * 7
    assert scanner_default.classify(_typed("nguoi_lap", "string", samples)).inferred_pii_type == PIIType.EMAIL.value


def test_phone_column_mixed_with_longer_numbers_is_phone(scanner_default):
    samples = ["0912345678"] * 7 + ["091234567890"] * 3
    assert scanner_default.classify(_typed("f17", "string", samples)).inferred_pii_type == PIIType.PHONE.value


def test_column_with_few_digit_matches_stays_undecided(scanner_default):
    samples = ["123456789012"] * 3 + ["ABC-1"] * 7
    assert scanner_default.classify(_typed("f17", "string", samples)) is None


def test_sentence_with_embedded_pii_is_free_text_under_any_name(scanner_default):
    samples = ["không có gì", "khách gọi 0912345678 nhé"]
    assert scanner_default.classify(_typed("f17", "string", samples)).inferred_pii_type == "FREE_TEXT_PII"


def test_json_string_with_pii_is_free_text(scanner_default):
    result = scanner_default.classify(_typed("payload", "string", ['{"phone":"0912345678"}']))
    assert result.inferred_pii_type == "FREE_TEXT_PII"


def test_all_null_column_is_empty_even_with_a_pii_name(scanner_default):
    assert scanner_default.classify(_typed("session_id", "string", [])).inferred_pii_type == "EMPTY_COLUMN"


@pytest.mark.parametrize(
    ("name", "samples", "expected_type"),
    [
        ("CustomerId", ["200800000001"], "CUSTOMER_ID"),
        ("SapCustomerId", ["2795220001"], "CUSTOMER_ID"),
        ("VehicleId", ["1HGCM82633A004352"], "VIN"),
        ("BatterySerial", ["ABC-123"], "DEVICE_SERIAL"),
        ("Imei", ["356938035643809"], "DEVICE_SERIAL"),
        ("f17", ["1HGCM82633A004352", "JH4KA7650MC000000"], "VIN"),
    ],
)
def test_customer_and_asset_identifiers(scanner_default, name, samples, expected_type):
    assert scanner_default.classify(_typed(name, "string", samples)).inferred_pii_type == expected_type


def test_seventeen_characters_with_forbidden_letter_is_not_a_vin(scanner_default):
    assert scanner_default.classify(_typed("f17", "string", ["1HGCM82633A00435O"])) is None


def test_boolean_is_not_personal_data(scanner_default):
    result = scanner_default.classify(_typed("EnterpriseCustomer", "boolean", ["True", "False"]))
    assert result.inferred_pii_type == "NOT_PERSONAL_DATA"
