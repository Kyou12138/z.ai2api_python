from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from jinja2 import Environment, FileSystemLoader
from starlette.requests import Request

from app.admin import api as admin_api
from app.admin import config_manager
from app.admin.config_manager import (
    CONFIG_FIELD_SPECS,
    build_config_page_data,
    build_form_updates,
    save_form_config,
    save_source_config,
    validate_env_source,
)
from app.services.runtime_config_dao import RuntimeConfigDAO


def _build_form_payload(**overrides):
    payload = {}

    for key, field in CONFIG_FIELD_SPECS.items():
        value = overrides[key] if key in overrides else field.default_value
        if field.value_type == "bool":
            if value:
                payload[key] = "on"
            continue
        payload[key] = "" if value is None else str(value)

    return payload


def _make_form_request(path: str, data: dict[str, str]) -> Request:
    body = urlencode(data, doseq=True).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (
                b"content-type",
                b"application/x-www-form-urlencoded",
            )
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_build_config_page_data_marks_database_and_env_sources():
    settings_stub = SimpleNamespace(
        API_ENDPOINT="https://example.com/v1/chat",
        TOOL_SUPPORT=False,
        AUTH_TOKEN="secret-auth",
        ADMIN_PASSWORD="secret-admin",
        uses_postgres=True,
        is_vercel=True,
    )

    page_data = build_config_page_data(
        settings_obj=settings_stub,
        runtime_overrides={
            "API_ENDPOINT": "https://example.com/v2/chat",
            "TOOL_SUPPORT": "false",
        },
    )

    assert page_data["overview"]["total_sections"] >= 6
    assert page_data["overview"]["database_overrides"] == 2
    assert page_data["overview"]["runtime_storage"] == "PostgreSQL"
    assert page_data["overview"]["is_vercel"] is True

    field_map = {
        field["key"]: field
        for section in page_data["sections"]
        for field in section["fields"]
    }

    assert field_map["API_ENDPOINT"]["source_label"] == "数据库"
    assert field_map["TOOL_SUPPORT"]["source_label"] == "数据库"
    assert field_map["AUTH_TOKEN"]["source_label"] == "环境变量"
    assert field_map["ADMIN_PASSWORD"]["sensitive"] is True


@pytest.mark.asyncio
async def test_save_form_config_persists_runtime_settings_to_database(
    tmp_path,
    monkeypatch,
):
    runtime_dao = RuntimeConfigDAO(str(tmp_path / "runtime_config.db"))
    monkeypatch.setattr(
        config_manager,
        "get_runtime_config_dao",
        lambda: runtime_dao,
    )

    reloaded = False

    async def fake_reload():
        nonlocal reloaded
        reloaded = True

    payload = _build_form_payload(
        API_ENDPOINT="https://db.example.com/v2/chat",
        TOOL_SUPPORT=False,
        TOKEN_AUTO_MAINTENANCE_ENABLED=True,
        TOKEN_AUTO_MAINTENANCE_INTERVAL=900,
        SERVICE_NAME="should-be-ignored",
        ADMIN_PASSWORD="should-also-be-ignored",
    )

    updates = await save_form_config(
        payload,
        reload_callback=fake_reload,
    )
    stored = await runtime_dao.get_settings()

    assert reloaded is True
    assert updates["API_ENDPOINT"] == "https://db.example.com/v2/chat"
    assert updates["TOOL_SUPPORT"] is False
    assert updates["TOKEN_AUTO_MAINTENANCE_ENABLED"] is True
    assert updates["TOKEN_AUTO_MAINTENANCE_INTERVAL"] == 900
    assert "SERVICE_NAME" not in updates
    assert "ADMIN_PASSWORD" not in updates
    assert stored["API_ENDPOINT"] == "https://db.example.com/v2/chat"
    assert stored["TOOL_SUPPORT"] == "False"
    assert stored["TOKEN_AUTO_MAINTENANCE_ENABLED"] == "True"
    assert stored["TOKEN_AUTO_MAINTENANCE_INTERVAL"] == "900"
    assert "SERVICE_NAME" not in stored
    assert "ADMIN_PASSWORD" not in stored


def test_build_form_updates_rejects_short_vercel_maintenance_interval(
    monkeypatch,
):
    monkeypatch.setenv("VERCEL", "1")

    with pytest.raises(ValueError, match="300"):
        build_form_updates(
            _build_form_payload(
                TOKEN_AUTO_MAINTENANCE_INTERVAL=299,
            )
        )


@pytest.mark.asyncio
async def test_save_source_config_raises_migration_error():
    with pytest.raises(RuntimeError, match="数据库运行时配置"):
        await save_source_config("SERVICE_NAME=new-service\n")


@pytest.mark.asyncio
async def test_save_config_endpoint_returns_refresh_trigger_and_persists_to_db(
    tmp_path,
    monkeypatch,
):
    runtime_dao = RuntimeConfigDAO(str(tmp_path / "runtime_config.db"))
    monkeypatch.setattr(
        config_manager,
        "get_runtime_config_dao",
        lambda: runtime_dao,
    )

    reloaded = False

    async def fake_reload():
        nonlocal reloaded
        reloaded = True

    monkeypatch.setattr(admin_api, "reload_settings", fake_reload)

    request = _make_form_request(
        "/admin/api/config/save",
        _build_form_payload(
            API_ENDPOINT="https://after.example.com/v1/chat",
            TOKEN_AUTO_MAINTENANCE_INTERVAL=1200,
        ),
    )
    response = await admin_api.save_config(request)
    body = response.body.decode("utf-8")
    stored = await runtime_dao.get_settings(
        ["API_ENDPOINT", "TOKEN_AUTO_MAINTENANCE_INTERVAL"]
    )

    assert response.status_code == 200
    assert response.headers["HX-Trigger"] == "admin-config-refresh"
    assert "保存成功" in body
    assert reloaded is True
    assert stored["API_ENDPOINT"] == "https://after.example.com/v1/chat"
    assert stored["TOKEN_AUTO_MAINTENANCE_INTERVAL"] == "1200"


@pytest.mark.asyncio
async def test_save_config_source_endpoint_returns_gone_notice():
    request = _make_form_request(
        "/admin/api/config/source",
        {"env_content": "SERVICE_NAME=after\nnot-valid-line\n"},
    )
    response = await admin_api.save_config_source(request)
    body = response.body.decode("utf-8")

    assert response.status_code == 410
    assert "数据库运行时配置" in body
    assert ".env" in body


def test_validate_env_source_always_rejects_direct_env_editing():
    with pytest.raises(ValueError, match="数据库运行时配置"):
        validate_env_source("SERVICE_NAME=ok\nbad line\n")


@pytest.mark.asyncio
async def test_env_preview_returns_migration_notice():
    response = await admin_api.get_env_preview()
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "不再支持在线编辑 .env" in body


def test_config_template_compiles():
    env = Environment(loader=FileSystemLoader("app/templates"))
    template = env.get_template("config.html")

    assert template is not None
