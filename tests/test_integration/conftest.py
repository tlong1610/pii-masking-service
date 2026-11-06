"""Fixture cho test cần stack docker compose. Đặt REQUIRE_DOCKER=1 để thiếu stack thì báo lỗi thay vì bỏ qua."""

import os

import httpx
import pytest
from pymongo import MongoClient

READONLY_URI = "mongodb://mockup_ro:mockup_ro@localhost:27017/mockup?authSource=admin"
SERVICE_URL = "http://localhost:8000"


def _unavailable(reason: str):
    if os.getenv("REQUIRE_DOCKER"):
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def readonly_client():
    client = MongoClient(os.getenv("MOCKUP_READONLY_URI", READONLY_URI), serverSelectionTimeoutMS=2000)
    try:
        if not client["mockup"].list_collection_names():
            _unavailable("MongoDB mockup chưa nạp dữ liệu")
    except Exception as exc:
        _unavailable(f"Không có MongoDB mockup: {type(exc).__name__}")
    yield client
    client.close()


@pytest.fixture(scope="module")
def service():
    client = httpx.Client(base_url=os.getenv("SERVICE_URL", SERVICE_URL), timeout=5)
    try:
        client.get("/health")
    except httpx.HTTPError as exc:
        _unavailable(f"Không có service: {type(exc).__name__}")
    yield client
    client.close()
