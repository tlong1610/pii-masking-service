from flashtext import KeywordProcessor

# Re-use EntityMatch from regex_ner
from piimask.detection.regex_ner import EntityMatch


class DictionaryNERScanner:
    """
    Tầng 2 cho luồng NER: Tìm kiếm dựa trên từ điển (Dictionary-based NER) thay thế cho BM25.
    Sử dụng thuật toán Aho-Corasick thông qua thư viện flashtext.
    Tốc độ O(N) theo chiều dài văn bản, không phụ thuộc số lượng từ khóa trong từ điển.
    Rất lý tưởng để quét danh sách Tên riêng, Địa danh, Tên bệnh viện, Tên thuốc...
    """

    def __init__(self, case_sensitive: bool = False):
        self.keyword_processor = KeywordProcessor(case_sensitive=case_sensitive)

    def load_dictionary(self, pii_type: str, keywords: list[str]):
        """
        Nạp một danh sách từ khóa vào bộ nhớ.
        Ví dụ: pii_type='LOCATION', keywords=['Hà Nội', 'TP.HCM', 'Đà Nẵng']
        """
        for keyword in keywords:
            # Liên kết từ khóa với pii_type.
            # Khi match, nó sẽ trả về tên pii_type thay vì chính từ khóa đó.
            self.keyword_processor.add_keyword(keyword, pii_type)

    def scan_text(self, text: str) -> list[EntityMatch]:
        """
        Quét và trả về tọa độ của các từ khóa có trong text.
        """
        matches = []
        if not text:
            return matches

        # span_info=True giúp flashtext trả về (clean_name, start_index, end_index)
        extracted = self.keyword_processor.extract_keywords(text, span_info=True)

        for item in extracted:
            pii_type, start, end = item
            # Lấy nguyên văn chuỗi match từ text gốc (giữ nguyên in hoa/thường)
            matched_text = text[start:end]

            matches.append(EntityMatch(start=start, end=end, pii_type=pii_type, text=matched_text))

        # Sắp xếp lại theo thứ tự xuất hiện trong text
        matches.sort(key=lambda x: x.start)
        return matches
