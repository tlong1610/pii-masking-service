"""Giá trị PII đánh dấu không được lọt ra log ứng dụng, thông báo lỗi và phản hồi API, kể cả khi che lỗi."""

import json
import logging
import sys

import mongomock
import pytest
from fastapi.testclient import TestClient

from api.main import app
from piimask.connectors.mongo_connector import MongoConnector
from tool import export as export_module
from tool.export import export_database

CANARIES = ["0912000111", "079199912345", "canary.pii@example.com"]
TEXT = f"Gọi {CANARIES[0]}, CCCD {CANARIES[1]}, email {CANARIES[2]}"
REQUEST = {"schemaVersion": 1, "requestId": "c-1", "context": "log", "locale": "vi", "text": TEXT}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def capture_everything(caplog):
    caplog.set_level(logging.DEBUG)


def _assert_clean(*outputs):
    for output in outputs:
        for canary in CANARIES:
            assert canary not in output


def _boom_with_value(*args, **kwargs):
    raise ValueError(f"không xử lý được: {TEXT}")


def test_ok_response_and_logs_have_no_canary(client, caplog, capsys):
    response = client.post("/v1/mask/text", json=REQUEST)
    assert response.json()["status"] == "OK"
    _assert_clean(response.text, caplog.text, *capsys.readouterr())


def test_mask_error_with_value_in_exception_stays_out_of_response_and_log(client, caplog, capsys, monkeypatch):
    monkeypatch.setattr("api.main.mask_text", _boom_with_value)
    response = client.post("/v1/mask/text", json=REQUEST)
    assert response.status_code == 500
    assert "ValueError" in caplog.text
    _assert_clean(response.text, caplog.text, *capsys.readouterr())


@pytest.mark.parametrize(
    "body",
    [
        {**REQUEST, "context": "khac"},
        {**REQUEST, "schemaVersion": TEXT},
        {**REQUEST, "requestId": TEXT * 3},
        {**REQUEST, "keep": TEXT},
        {"text": TEXT},
        [TEXT],
    ],
)
def test_validation_error_does_not_echo_request(client, caplog, capsys, body):
    response = client.post("/v1/mask/text", json=body)
    assert response.status_code == 422
    _assert_clean(response.text, caplog.text, *capsys.readouterr())


def test_malformed_json_does_not_echo_request(client, caplog):
    response = client.post(
        "/v1/mask/text", content=f'{{"text": "{TEXT}"'.encode(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    _assert_clean(response.text, caplog.text)


def _connector():
    client = mongomock.MongoClient()
    document = {"PhoneNumber": CANARIES[0], "IdNumber": CANARIES[1], "Email": CANARIES[2], "Note": TEXT}
    client["src"]["khach"].insert_one(document)
    return MongoConnector("mongodb://mockup", database_name="src", client=client)


def test_export_output_and_logs_have_no_canary(tmp_path, caplog, capsys):
    export_database(_connector(), tmp_path, secret="s", key_version="v1", formats=["csv"])
    files = [path.read_text(encoding="utf-8-sig") for path in tmp_path.iterdir()]
    _assert_clean(*files, caplog.text, *capsys.readouterr())


def test_redact_error_in_export_withholds_the_cell(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr("piimask.transform.mask_engine.mask_text", _boom_with_value)
    export_database(_connector(), tmp_path, secret="s", key_version="v1", formats=["csv"])
    files = [path.read_text(encoding="utf-8-sig") for path in tmp_path.iterdir()]
    assert "[REDACTED]" in files[0] or "[REDACTED]" in files[1]
    _assert_clean(*files, caplog.text)


def test_guard_error_in_export_withholds_the_cell(tmp_path, caplog, monkeypatch):
    monkeypatch.setattr("piimask.transform.mask_engine._guard_text", _boom_with_value)
    client = mongomock.MongoClient()
    client["src"]["khach"].insert_many([{"amount": "100"}, {"amount": "200"}, {"amount": f"gọi {CANARIES[0]}"}])
    connector = MongoConnector("mongodb://mockup", database_name="src", client=client)
    export_database(connector, tmp_path, secret="s", key_version="v1", formats=["csv"])
    _assert_clean(*[path.read_text(encoding="utf-8-sig") for path in tmp_path.iterdir()], caplog.text)


def test_cli_failure_prints_error_type_only(monkeypatch, tmp_path):
    monkeypatch.setattr(export_module, "export_database", _boom_with_value)
    monkeypatch.setattr(export_module, "MongoClient", lambda *args, **kwargs: mongomock.MongoClient())
    monkeypatch.setenv("HMAC_SECRET", "s")
    export_module.get_settings.cache_clear()
    monkeypatch.setattr(sys, "argv", ["tool.export", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as failure:
        export_module.main()
    export_module.get_settings.cache_clear()
    assert str(failure.value) == "Xuất thất bại: ValueError"


def test_report_is_valid_json_without_canary(tmp_path):
    export_database(_connector(), tmp_path, secret="s", key_version="v1", formats=["csv"])
    report = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert json.loads(report)["collections"]["khach"]["documents"] == 1
    _assert_clean(report)
