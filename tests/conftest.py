import os

import pytest

# Chỉ dùng regex và từ điển trong test: không tải mô hình, kết quả ổn định.
os.environ.setdefault("ENABLE_NER", "false")


@pytest.fixture
def live_mongo():
    """Bỏ qua nếu không có MongoDB mockup đang chạy (docker compose)."""
    MongoClient = pytest.importorskip("pymongo").MongoClient

    uri = os.getenv("MONGO_URI", "mongodb://admin:admin@localhost:27017/?authSource=admin")
    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
        client[os.getenv("MONGO_DB", "mydatabase")].list_collection_names()
    except Exception as exc:
        pytest.skip(f"Không có MongoDB mockup: {type(exc).__name__}")
    yield client
    client.close()
