"""Sinh từng giá trị giả theo seed. Không lấy giá trị từ bản mẫu của mentor, chỉ giữ đúng định dạng."""

import random
import unicodedata
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from faker import Faker

_PHONE_PREFIXES = ["032", "033", "034", "038", "056", "070", "077", "081", "085", "091", "094", "097", "098"]
_PROVINCE_CODES = ["001", "019", "022", "026", "030", "033", "034", "036", "038", "040", "048", "079", "092"]
_EMAIL_DOMAINS = ["example.com", "example.net", "mail.example.vn"]
_PROVINCES = ["Hà Nội", "Hải Phòng", "Đà Nẵng", "Nghệ An", "Thanh Hóa", "Cần Thơ", "Thành phố Hồ Chí Minh"]
_DISTRICTS = ["Long Biên", "Ứng Hòa", "Thanh Xuân", "Hải Châu", "Ninh Kiều", "Quỳnh Lưu", "Thủ Đức"]
_WARDS = ["Trầm Lộng", "Bồ Đề", "Thạch Bàn", "An Khánh", "Tân Phong", "Hòa Cường", "Mỹ Đình"]
_STREETS = ["Nguyễn Trãi", "Lê Lợi", "Trần Phú", "Hoàng Diệu", "Quang Trung", "Lý Thường Kiệt"]
_COMPANY_WORDS = ["Minh Anh", "Hưng Thịnh", "Đại Phát", "Sao Mai", "Thành Công", "An Bình"]

_BASE_DATE = datetime(2024, 1, 1, tzinfo=UTC)


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("Đ", "D").replace("đ", "d"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


class FakeValues:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.faker = Faker("vi_VN")
        self.faker.seed_instance(seed)

    def digits(self, count: int) -> str:
        return "".join(self.rng.choice("0123456789") for _ in range(count))

    def full_name(self) -> str:
        name = self.faker.name()
        return name.upper() if self.rng.random() < 0.3 else name

    def cccd(self) -> str:
        return f"{self.rng.choice(_PROVINCE_CODES)}{self.rng.choice('0123')}{self.digits(8)}"

    def phone(self) -> str:
        """Số 10 chữ số, xen số 12 chữ số như trong bản mẫu hợp đồng."""
        length = 12 if self.rng.random() < 0.2 else 10
        return self.rng.choice(_PHONE_PREFIXES) + self.digits(length - 3)

    def email(self, name: str) -> str:
        parts = strip_accents(name).lower().split()
        return f"{parts[-1]}{parts[0][0]}{self.digits(3)}@{self.rng.choice(_EMAIL_DOMAINS)}"

    def staff_email(self) -> str:
        return self.email(self.faker.name()).split("@")[0].upper() + "@staff.example.vn"

    def address(self) -> str:
        number = self.rng.randint(1, 300)
        street, ward = self.rng.choice(_STREETS), self.rng.choice(_WARDS)
        district, province = self.rng.choice(_DISTRICTS), self.rng.choice(_PROVINCES)
        formats = [
            f"Số {number} {street}, Phường {ward}, Quận {district}, {province}, Việt Nam",
            f"Thôn {ward}, Xã {ward}-Huyện {district}-{province}-Việt Nam",
            f"{number} {street}, {district}, {province}",
        ]
        return self.rng.choice(formats)

    def company_name(self) -> str:
        return f"Công ty TNHH {self.rng.choice(_COMPANY_WORDS)} {self.digits(2)}"

    def personal_tax_code(self) -> str:
        return "8" + self.digits(9)

    def company_tax_code(self) -> str:
        return "0" + self.digits(9) + self.rng.choice(["", f"-{self.digits(3)}"])

    def bank_account(self) -> str:
        return self.digits(self.rng.choice([10, 12, 14]))

    def card_number(self) -> str:
        body = "9704" + self.digits(11)
        total = 0
        for index, digit in enumerate(reversed(body)):
            value = int(digit) * (2 if index % 2 == 0 else 1)
            total += value - 9 if value > 9 else value
        return body + str((10 - total % 10) % 10)

    def vin(self) -> str:
        return "DEMO" + "".join(self.rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(13))

    def object_id(self) -> ObjectId:
        return ObjectId(bytes(self.rng.getrandbits(8) for _ in range(12)))

    def hex_upper(self, length: int) -> str:
        return "".join(self.rng.choice("0123456789ABCDEF") for _ in range(length))

    def date(self, start: datetime = _BASE_DATE, days: int = 700) -> datetime:
        millis = self.rng.randrange(days * 86_400_000)
        return start + timedelta(milliseconds=millis)

    def birth_date(self) -> datetime:
        return datetime(1960, 1, 1, tzinfo=UTC) + timedelta(days=self.rng.randrange(16_000))
