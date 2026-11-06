import re

from pydantic import BaseModel


class EntityMatch(BaseModel):
    start: int
    end: int
    pii_type: str
    text: str

class RegexNERScanner:
    """
    Tầng 1 của phễu che văn bản tự do.
    Nhiệm vụ: Trích xuất các thực thể nhạy cảm (PII) dựa trên Regex và Rule từ bên trong khối văn bản dài (Free-text).
    Thay vì trả về kết quả cho cả cột, module này trả về chính xác vị trí (start, end) của thực thể để tiến hành mask/redact.
    """
    def __init__(self):
        # Biểu thức chính quy tìm kiếm bên trong text (không dùng ^ và $ như RuleBasedScanner)
        self.patterns = {
            "PHONE": re.compile(r"(?<!\d)(0|84|\+84)[35789]\d{8}(?!\d)"),
            "EMAIL": re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
            "CCCD": re.compile(r"(?<!\d)\d{12}(?!\d)"),
            # Bắt số thẻ tín dụng cơ bản 16 số, có thể có dấu - hoặc khoảng trắng
            "CREDIT_CARD": re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)"),
            "TAX_CODE": re.compile(r"(?<!\d)\d{10}(?:-\d{3})?(?!\d)")
        }

    def scan_text(self, text: str) -> list[EntityMatch]:
        matches = []
        if not text:
            return matches

        for pii_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                overlap = False
                for m in matches:
                    if max(start, m.start) < min(end, m.end):
                        overlap = True
                        break
                if not overlap:
                    matches.append(EntityMatch(
                        start=start,
                        end=end,
                        pii_type=pii_type,
                        text=match.group()
                    ))

        # Sort matches by start position
        matches.sort(key=lambda x: x.start)
        return matches
