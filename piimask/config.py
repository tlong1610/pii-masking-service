"""Cấu hình lõi piimask, đọc từ biến môi trường (tiền tố không bắt buộc) hoặc file .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_HMAC_SECRET = "dev-hmac-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Tầng NER bằng mô hình GLiNER cho văn bản tự do; tắt thì chỉ dùng regex và từ điển.
    enable_ner: bool = False
    ner_model_name: str = "urchade/gliner_multi_pii-v1"
    # File từ điển (mỗi dòng một từ khoá) cho tầng từ điển; để trống thì bỏ qua.
    ner_dictionary_path: str = ""

    # Khoá HMAC giữ khả năng nối giữa các bảng. Bắt buộc đổi khi chạy thật.
    hmac_secret: str = DEV_HMAC_SECRET
    hmac_key_version: str = "v1"

    # Nguồn MongoDB của tool. Luôn dùng tài khoản chỉ đọc.
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "mockup"


@lru_cache
def get_settings() -> Settings:
    return Settings()
