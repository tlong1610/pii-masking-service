from piimask.detection.regex_ner import RegexNERScanner


def test_regex_ner_scanner():
    scanner = RegexNERScanner()

    text = "Khách hàng Nguyễn Văn A có số điện thoại là 0901234567, cccd 012345678901 và email nguyen.van.a@gmail.com. Mã số thuế 1234567890."

    matches = scanner.scan_text(text)

    print(f"Found {len(matches)} matches:")
    for m in matches:
        print(f"- {m.pii_type}: '{m.text}' at [{m.start}:{m.end}]")

    assert len(matches) == 4

    # Sort matches to assert in order
    matches_sorted = sorted(matches, key=lambda x: x.start)

    assert matches_sorted[0].pii_type == "PHONE"
    assert matches_sorted[0].text == "0901234567"

    assert matches_sorted[1].pii_type == "CCCD"
    assert matches_sorted[1].text == "012345678901"

    assert matches_sorted[2].pii_type == "EMAIL"
    assert matches_sorted[2].text == "nguyen.van.a@gmail.com"

    assert matches_sorted[3].pii_type == "TAX_CODE"
    assert matches_sorted[3].text == "1234567890"

    print("All Regex NER tests passed!")

if __name__ == "__main__":
    test_regex_ner_scanner()
