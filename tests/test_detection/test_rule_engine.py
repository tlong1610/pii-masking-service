import pytest

from piimask.detection.rule_engine import RuleBasedScanner
from piimask.detection.taxonomy import PIIType
from piimask.schemas import ColumnProfile


@pytest.fixture
def scanner():
    return RuleBasedScanner(match_threshold=0.5)


def test_tracking_code_not_cccd(scanner):
    # Tracking code giống CCCD (12 số) không được tính là CCCD
    profile = ColumnProfile(
        column_name="tracking_code",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["400691172582", "123456789012"],
        system_recommendation=None
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.TRACKING_CODE.value
    assert result.recommended_action == "KEEP"


def test_order_id_not_pii(scanner):
    # order id không phải PII
    profile = ColumnProfile(
        column_name="order_id",
        data_type="string",
        is_primary_key=True,
        is_foreign_key=False,
        samples=["ORD123", "ORD456"],
        system_recommendation=None
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.TRACKING_CODE.value
    assert result.recommended_action == "KEEP"


def test_org_email_detected_as_email(scanner):
    # email tổ chức
    profile = ColumnProfile(
        column_name="contact_email",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["support@company.vn", "contact@exoticliquids.co.uk"],
        system_recommendation=None
    )
    result = scanner.classify(profile)
    # Rule engine bắt bằng regex email nên sẽ ra EMAIL.
    # LLM sẽ đánh giá là personal hay non_personal sau.
    assert result.inferred_pii_type == PIIType.EMAIL.value


def test_money_alone_non_personal(scanner):
    # số tiền đứng riêng non_personal
    profile = ColumnProfile(
        column_name="total_amount",
        data_type="float",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["1000.50", "200.0"],
        system_recommendation=None
    )
    result = scanner.classify(profile)
    assert result.inferred_pii_type == PIIType.MONEY_ALONE.value
    assert result.recommended_action == "KEEP"


def test_cccd_regex_strict_12_digits(scanner):
    # Đảm bảo CCCD phải đúng 12 số
    profile_9_digits = ColumnProfile(
        column_name="unknown_col",
        data_type="string",
        is_primary_key=False,
        is_foreign_key=False,
        samples=["123456789"],  # CMND cũ 9 số
        system_recommendation=None
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
        system_recommendation=None
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
        system_recommendation=None
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
    assert result.recommended_action != "KEEP"


def test_personal_id_names_are_not_treated_as_technical_keys(scanner):
    result = scanner.classify(_profile("patient_id", ["BN-0001", "BN-0002"]))
    assert result is not None
    assert result.inferred_pii_type == "PATIENT_ID"
    assert result.recommended_action != "KEEP"


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
    assert supplier_tax.recommended_action == "KEEP"

    kyc = scanner.classify(_profile("ocr_text", ["CONG HOA XA HOI"], table="kyc_documents"))
    assert kyc.recommended_action == "DROP"


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
    assert result.recommended_action == "KEEP"


def test_birth_date_is_still_dob(scanner):
    result = scanner.classify(_typed("birth_date", "date", ["1980-01-01"]))
    assert result.inferred_pii_type == PIIType.DOB.value


def test_empty_column_is_proposed_for_drop(scanner):
    result = scanner.classify(_typed("customer_desc", "text", []))
    assert result.inferred_pii_type == "EMPTY_COLUMN"
    assert result.recommended_action == "DROP"


@pytest.mark.parametrize(
    ("name", "expected_type", "expected_action"),
    [
        ("ship_country", "NOT_PERSONAL_DATA", "KEEP"),
        ("state_name", "NOT_PERSONAL_DATA", "KEEP"),
        ("territory_description", "NOT_PERSONAL_DATA", "KEEP"),
        ("ship_city", "CITY", "KEEP"),
    ],
)
def test_geography_levels(scanner, name, expected_type, expected_action):
    result = scanner.classify(_typed(name, "character varying", ["Hà Nội", "Lyon"]))
    assert (result.inferred_pii_type, result.recommended_action) == (expected_type, expected_action)


@pytest.mark.parametrize(
    ("name", "expected_type", "expected_action"),
    [
        ("first_name", "FULL_NAME", "MASK"),
        ("last_name", "FULL_NAME", "MASK"),
        ("contact_name", "FULL_NAME", "MASK"),
        ("ship_name", "FULL_NAME", "MASK"),
        ("ho_ten", "FULL_NAME", "MASK"),
        ("product_name", "NOT_PERSONAL_DATA", "KEEP"),
        ("category_name", "NOT_PERSONAL_DATA", "KEEP"),
        ("shipper_name", "NOT_PERSONAL_DATA", "KEEP"),
        ("ten_san_pham", "NOT_PERSONAL_DATA", "KEEP"),
    ],
)
def test_name_columns_are_classified_by_their_entity(scanner, name, expected_type, expected_action):
    result = scanner.classify(_typed(name, "character varying", ["Alpha Beta"]))
    assert (result.inferred_pii_type, result.recommended_action) == (expected_type, expected_action)


@pytest.mark.parametrize("name", ["name", "display_name", "user_name"])
def test_unclear_name_columns_are_left_to_the_llm(scanner, name):
    assert scanner.classify(_typed(name, "character varying", ["Alpha Beta"])) is None
