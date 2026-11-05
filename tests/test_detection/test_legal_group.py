from piimask.detection.taxonomy import legal_group


def test_cccd_is_basic_not_sensitive():
    assert legal_group("CCCD") == "co_ban"


def test_financial_and_credential_types_are_sensitive():
    for pii_type in ("BANK_ACCOUNT", "CREDIT_CARD", "PASSWORD", "TOKEN", "GPS"):
        assert legal_group(pii_type) == "nhay_cam"


def test_unlisted_type_falls_back_to_basic():
    assert legal_group("CUSTOMER_ID") == "co_ban"


def test_non_personal_has_no_group():
    assert legal_group(None) is None
