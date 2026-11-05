import os
import re

# Khắc phục lỗi OpenMP duplicate runtime trên môi trường Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from piimask.detection.regex_ner import EntityMatch

# GLiNER reads at most max_len words (384 for gliner_multi_pii) and drops the rest; chunks stay well below
# that so the subword count also fits the encoder's 512-token window.
MAX_CHUNK_TOKENS = 300
_GLINER_WORD = re.compile(r"\w+(?:[-_]\w+)*|\S")
_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]*\s*|[.!?\n]+\s*")
_WORD = re.compile(r"\S+\s*|\s+")


class MLNERScanner:
    """
    Tầng 3 cho luồng NER: Mô hình Zero-Shot NER dựa trên kiến trúc GLiNER.
    Sử dụng GLiNER Multi-PII (~300MB) để nhận diện các loại thực thể PII
    linh hoạt theo nhãn tùy chỉnh (Open-Vocabulary NER), không bị giới hạn
    ở 3 nhãn cứng PER/LOC/ORG như các model Token Classification truyền thống.

    Ưu điểm so với ViElectra cũ:
    - Zero-shot: Không cần fine-tune, khai báo nhãn tại inference time.
    - Đa ngôn ngữ: Hỗ trợ tốt tiếng Việt, tiếng Anh và nhiều ngôn ngữ khác.
    - Offset chính xác: Trả về start/end offset chính xác, không bị lệch sub-word.
    - Mở rộng dễ dàng: Thêm nhãn mới chỉ cần thêm vào danh sách labels.
    """
    # Bảng ánh xạ nhãn GLiNER -> nhãn PII nội bộ của hệ thống
    LABEL_MAPPING = {
        "person": "PERSON_NAME",
        "location": "LOCATION",
        "address": "LOCATION",
        "organization": "ORGANIZATION",
        "phone number": "PHONE",
        "email": "EMAIL",
        "id document": "CCCD",
        "credit card number": "CREDIT_CARD",
        "bank account": "BANK_ACCOUNT",
        "date of birth": "DATE_OF_BIRTH",
    }

    def __init__(
        self,
        model_name: str = "urchade/gliner_multi_pii-v1",
        labels: list[str] | None = None,
        threshold: float = 0.35,
    ):
        try:
            from gliner import GLiNER
        except ImportError:
            raise ImportError(
                "Vui lòng cài đặt gliner: pip install gliner"
            )

        # Khởi tạo model GLiNER. Lần chạy đầu sẽ tải weights (~300MB) từ HuggingFace Hub.
        self.model = GLiNER.from_pretrained(model_name)
        self.threshold = threshold

        # Danh sách nhãn mặc định bao phủ các loại PII phổ biến nhất trong nghiệp vụ
        self.labels = labels or [
            "person",
            "location",
            "organization",
            "phone number",
            "email",
            "id document",
            "credit card number",
            "bank account",
            "date of birth",
            "address",
        ]

    def scan_text(self, text: str) -> list[EntityMatch]:
        """
        Quét văn bản và trả về danh sách các thực thể PII được nhận diện.

        GLiNER trả về list[dict], mỗi dict có dạng:
            {'start': 10, 'end': 22, 'text': 'Nguyễn Văn A', 'label': 'person', 'score': 0.95}
        """
        matches = []
        if not text:
            return matches

        # Dự đoán thực thể với ngưỡng confidence. GLiNER silently truncates input past its length limit,
        # so long text is scanned chunk by chunk and offsets are shifted back to the full text.
        entities = []
        for offset, chunk in self._chunks(text):
            for ent in self.model.predict_entities(chunk, self.labels, threshold=self.threshold):
                entities.append({**ent, "start": ent["start"] + offset, "end": ent["end"] + offset})

        for ent in entities:
            word = ent.get("text", "")
            # Bỏ qua nếu mô hình nhận diện nhầm các Tag đã chèn từ Tầng 1 và 2
            if any(
                tag in word
                for tag in [
                    "PERSON", "LOCATION", "ORGANIZATION",
                    "PHONE", "EMAIL", "CCCD",
                ]
            ):
                continue

            # Chuyển đổi nhãn GLiNER sang cấu trúc Taxonomy của hệ thống PII
            label = ent.get("label", "").lower()
            pii_type = self.LABEL_MAPPING.get(label, label.upper())

            matches.append(
                EntityMatch(
                    start=ent["start"],
                    end=ent["end"],
                    pii_type=pii_type,
                    text=word,
                )
            )

        # Sắp xếp kết quả theo thứ tự xuất hiện
        matches.sort(key=lambda x: x.start)
        return matches

    def _token_count(self, text: str) -> int:
        # GLiNER counts words (punctuation is a word of its own), not subword tokens.
        return len(_GLINER_WORD.findall(text))

    def _chunks(self, text: str) -> list[tuple[int, str]]:
        """(offset, chunk) pieces of text, each under MAX_CHUNK_TOKENS, cut at sentence ends.

        A sentence that is itself too long is cut between words, so an entity is only split when one
        sentence alone exceeds the model limit.
        """
        if self._token_count(text) <= MAX_CHUNK_TOKENS:
            return [(0, text)]
        units: list[tuple[int, int]] = []
        for sentence in _SENTENCE.finditer(text):
            if self._token_count(sentence.group()) <= MAX_CHUNK_TOKENS:
                units.append(sentence.span())
            else:
                units.extend((sentence.start() + w.start(), sentence.start() + w.end())
                             for w in _WORD.finditer(sentence.group()))
        chunks: list[tuple[int, str]] = []
        start = end = units[0][0]
        for unit_start, unit_end in units:
            if end > start and self._token_count(text[start:unit_end]) > MAX_CHUNK_TOKENS:
                chunks.append((start, text[start:end]))
                start = unit_start
            end = unit_end
        chunks.append((start, text[start:end]))
        return chunks
