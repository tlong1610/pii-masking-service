import re

from pydantic import BaseModel

# Giá trị sau khóa: trong dấu nháy lấy tới dấu nháy đóng; không nháy thì lấy tới khoảng trắng, dấu & hoặc dấu nháy,
# bỏ dấu câu ở cuối.
_VALUE = r"""(?:"([^"]+)"|'([^']+)'|([^\s&"']*[^\s&"',;.]))"""
_ASSIGN = r"""["']?\s*[=:]\s*"""
# Giá trị đứng sau khóa chỉ cách bằng khoảng trắng phải giống mã (có chữ số), để "token hết hạn" không bị che.
_CODE = r"(?=[^\s]*\d)([A-Za-z0-9_\-.+/=]{8,})"

_PASSWORD_KEYS = r"pass(?:word|wd|phrase)?|pwd|mat[_-]?khau|mật khẩu"
_TOKEN_KEYS = (
    r"(?:access|refresh|id|auth|bearer|csrf)[_-]?token|token|x-api-key|api[_-]?key|"
    r"(?:client|app|aws)?[_-]?secret(?:[_-]?(?:access[_-]?)?key)?|private[_-]?key"
)
_SESSION_KEYS = r"(?:j|php|asp)?session(?:[_-]?id)?|sess(?:ion)?id|sid"
_OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_HEX = r"[0-9a-fA-F]{1,4}"
_COORDINATE = r"-?\d{1,3}\.\d{4,}"


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
        # Bí mật đứng trước để không bị số điện thoại hay CCCD cắt ngang. Mẫu có nhóm bắt thì chỉ che phần trong nhóm,
        # giữ nguyên tên khóa.
        self.patterns = {
            "PASSWORD": re.compile(rf"(?i)(?<![\w-])(?:{_PASSWORD_KEYS}){_ASSIGN}{_VALUE}"),
            "TOKEN": re.compile(
                rf"(?i)(?<![\w-])(?:{_TOKEN_KEYS}){_ASSIGN}{_VALUE}"
                rf"|(?i:\b(?:bearer|basic)\s+)([A-Za-z0-9._~+/=-]{{8,}})"
                rf"|(?<![\w-])(?i:token)\s+{_CODE}"
                r"|\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]*"
            ),
            "SESSION_ID": re.compile(
                rf"(?i)(?<![\w-])(?:{_SESSION_KEYS}){_ASSIGN}{_VALUE}|(?<![\w-])(?i:session)\s+{_CODE}"
            ),
            "GPS": re.compile(
                rf"(?<![\d.\w]){_COORDINATE}\s*,\s*{_COORDINATE}(?![\d.])"
                rf"|(?i:(?<![\w-])(?:lat(?:itude)?|lng|lon(?:g|gitude)?){_ASSIGN})[\"']?(-?\d{{1,3}}\.\d+)"
            ),
            "IP_ADDRESS": re.compile(
                rf"(?<![\w.])(?:{_OCTET}\.){{3}}{_OCTET}(?![\w.]|\.\d)"
                rf"|(?<![\w:])(?:{_HEX}:){{7}}{_HEX}(?![\w:])"
                rf"|(?<![\w:])(?:{_HEX}:){{1,6}}:(?:{_HEX}(?::{_HEX})*)?(?![\w:])"
            ),
            "PHONE": re.compile(r"(?<!\d)(?:0|84|\+84)[35789]\d{8}(?!\d)"),
            "EMAIL": re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b"),
            "CCCD": re.compile(r"(?<!\d)\d{12}(?!\d)"),
            # Bắt số thẻ tín dụng cơ bản 16 số, có thể có dấu - hoặc khoảng trắng
            "CREDIT_CARD": re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)"),
            "TAX_CODE": re.compile(r"(?<!\d)\d{10}(?:-\d{3})?(?!\d)"),
        }

    def scan_text(self, text: str) -> list[EntityMatch]:
        matches = []
        if not text:
            return matches

        for pii_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                group = next((index for index, value in enumerate(match.groups(), 1) if value is not None), 0)
                start, end = match.span(group)
                overlap = False
                for m in matches:
                    if max(start, m.start) < min(end, m.end):
                        overlap = True
                        break
                if not overlap:
                    matches.append(EntityMatch(start=start, end=end, pii_type=pii_type, text=match.group(group)))

        # Sort matches by start position
        matches.sort(key=lambda x: x.start)
        return matches
