"""Gọi service từ ngoài container qua cổng đã mở."""

import subprocess

import pytest

CANARY = "0912000999"
REQUEST = {"schemaVersion": 1, "requestId": "it-1", "context": "ticket", "locale": "vi", "keep": ["METER_ID"]}


def test_health_from_outside_container(service):
    response = service.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "OK"


def test_mask_from_outside_container(service):
    response = service.post("/v1/mask/text", json={**REQUEST, "text": f"gọi {CANARY}, công tơ DEMO-001"})
    assert response.status_code == 200
    assert response.json()["maskedText"] == "gọi [PHONE], công tơ DEMO-001"


def test_openapi_from_outside_container(service):
    assert "/v1/mask/text" in service.get("/openapi.json").json()["paths"]


def test_container_log_has_no_canary(service):
    service.post("/v1/mask/text", json={**REQUEST, "text": f"gọi {CANARY}"})
    service.post("/v1/mask/text", json={**REQUEST, "context": "khac", "text": f"gọi {CANARY}"})
    logs = subprocess.run(["docker", "compose", "logs", "service"], capture_output=True, text=True)
    if logs.returncode != 0:
        pytest.skip("Không đọc được log container")
    assert "POST /v1/mask/text" in logs.stdout
    assert CANARY not in logs.stdout + logs.stderr
