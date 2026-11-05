from piimask.detection.dict_ner import DictionaryNERScanner


def test_dict_ner_scanner():
    scanner = DictionaryNERScanner(case_sensitive=False)

    # Nạp từ điển mẫu
    scanner.load_dictionary("LOCATION", ["Hà Nội", "Hồ Chí Minh", "Đà Nẵng"])
    scanner.load_dictionary("HOSPITAL", ["Bệnh viện Bạch Mai", "Viện tim mạch", "Chợ Rẫy"])

    # Text cần kiểm tra (Free-text)
    text = "Bệnh nhân Nguyễn Văn A chuyển từ bệnh viện Bạch Mai về Hà Nội để tiếp tục điều trị tại viện tim mạch."

    # Quét
    matches = scanner.scan_text(text)

    print(f"Found {len(matches)} matches:")
    for m in matches:
        print(f"- {m.pii_type}: '{m.text}' at [{m.start}:{m.end}]")

    assert len(matches) == 3

    assert matches[0].pii_type == "HOSPITAL"
    assert matches[0].text.lower() == "bệnh viện bạch mai"

    assert matches[1].pii_type == "LOCATION"
    assert matches[1].text.lower() == "hà nội"

    assert matches[2].pii_type == "HOSPITAL"
    assert matches[2].text.lower() == "viện tim mạch"

    print("All Dictionary NER tests passed!")

if __name__ == "__main__":
    test_dict_ner_scanner()

