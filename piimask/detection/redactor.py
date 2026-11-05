
from piimask.detection.regex_ner import EntityMatch


class TextRedactor:
    """
    Module hỗ trợ che mờ văn bản (Masking/Redacting) dựa trên tọa độ của thực thể.
    """
    @staticmethod
    def redact(text: str, matches: list[EntityMatch]) -> str:
        """
        Thay thế các thực thể nhạy cảm bằng tag tương ứng.
        Ví dụ: "Số của tôi là 0901234567" -> "Số của tôi là [PHONE]"

        Để tránh việc thay thế làm sai lệch tọa độ (index) của các thực thể phía sau,
        ta thực hiện thay thế từ cuối chuỗi ngược lên đầu chuỗi.
        """
        # Sắp xếp từ cuối lên đầu
        matches_sorted = sorted(matches, key=lambda x: x.start, reverse=True)

        redacted_text = text
        for m in matches_sorted:
            replacement = f"[{m.pii_type}]"
            redacted_text = redacted_text[:m.start] + replacement + redacted_text[m.end:]

        return redacted_text

