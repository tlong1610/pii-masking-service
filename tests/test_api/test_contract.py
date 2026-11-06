"""Phản hồi thật phải khớp hợp đồng OpenAPI đã commit ở docs/api/openapi-v1.json."""

import json

import jsonschema
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.openapi import CONTRACT_PATH, render

REQUEST = {
    "schemaVersion": 1,
    "requestId": "r-1",
    "context": "ticket",
    "locale": "vi",
    "text": "gọi 0912345678 công tơ DEMO-001",
    "keep": ["METER_ID"],
}


@pytest.fixture(scope="module")
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _assert_matches(contract, path, method, response):
    media = contract["paths"][path][method]["responses"][str(response.status_code)]["content"]["application/json"]
    # Bọc schema trong tài liệu hợp đồng để $ref trỏ được tới components.
    schema = {**media["schema"], "components": contract["components"]}
    jsonschema.validate(response.json(), schema)


def test_committed_contract_matches_generated_openapi():
    assert CONTRACT_PATH.read_text(encoding="utf-8") == render(), (
        "Đổi hợp đồng: chạy python -m api.openapi, tăng phiên bản"
    )


def test_health(client, contract):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "OK"
    _assert_matches(contract, "/health", "get", response)


def test_mask_ok(client, contract):
    response = client.post("/v1/mask/text", json=REQUEST)
    assert response.status_code == 200
    _assert_matches(contract, "/v1/mask/text", "post", response)
    body = response.json()
    assert body["status"] == "OK" and body["requestId"] == "r-1"
    assert body["maskedText"] == "gọi [PHONE] công tơ DEMO-001"
    assert body["entities"] == [{"type": "PHONE", "start": 4, "end": 14}]


def test_keep_is_optional(client):
    request = {key: value for key, value in REQUEST.items() if key != "keep"}
    assert client.post("/v1/mask/text", json=request).status_code == 200


def test_keep_type_is_not_masked(client):
    response = client.post("/v1/mask/text", json={**REQUEST, "keep": ["PHONE"]})
    assert "0912345678" in response.json()["maskedText"]


@pytest.mark.parametrize("context", ["faq", "ocr", "ticket", "log"])
def test_every_context_is_accepted(client, context):
    assert client.post("/v1/mask/text", json={**REQUEST, "context": context}).status_code == 200


@pytest.mark.parametrize(
    "change",
    [{"context": "khac"}, {"schemaVersion": 2}, {"requestId": ""}, {"text": 123}, {"keep": "METER_ID"}],
)
def test_invalid_request_is_rejected(client, contract, change):
    response = client.post("/v1/mask/text", json={**REQUEST, **change})
    assert response.status_code == 422
    _assert_matches(contract, "/v1/mask/text", "post", response)
    assert response.json()["status"] == "INVALID_REQUEST"
    assert "maskedText" not in response.json()


def test_mask_failure_fails_closed(client, contract, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("lỗi tầng phát hiện")

    monkeypatch.setattr("api.main.mask_text", boom)
    response = client.post("/v1/mask/text", json=REQUEST)
    assert response.status_code == 500
    _assert_matches(contract, "/v1/mask/text", "post", response)
    body = response.json()
    assert body["status"] == "ERROR" and body["requestId"] == "r-1"
    assert "maskedText" not in body


def test_health_reports_failure(client, contract, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("hỏng")

    monkeypatch.setattr("api.main.mask_text", boom)
    response = client.get("/health")
    assert response.status_code == 503
    _assert_matches(contract, "/health", "get", response)
    assert response.json()["status"] == "ERROR"


def test_openapi_is_served(client):
    assert set(client.get("/openapi.json").json()["paths"]) == {"/health", "/v1/mask/text"}
