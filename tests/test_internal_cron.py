import json

import pytest
from fastapi import HTTPException

from app.core import internal
from app.services.token_automation import TokenMaintenanceSummary


@pytest.mark.asyncio
async def test_internal_cron_requires_matching_secret(monkeypatch):
    monkeypatch.setattr(internal.settings, "CRON_SECRET", "expected-secret")

    with pytest.raises(HTTPException) as exc_info:
        await internal.run_scheduled_token_maintenance(
            authorization="Bearer wrong-secret"
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_internal_cron_returns_disabled_when_auto_maintenance_off(
    monkeypatch,
):
    monkeypatch.setattr(internal.settings, "CRON_SECRET", "expected-secret")
    monkeypatch.setattr(
        internal.settings,
        "TOKEN_AUTO_MAINTENANCE_ENABLED",
        False,
    )

    response = await internal.run_scheduled_token_maintenance(
        authorization="Bearer expected-secret"
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 200
    assert payload["status"] == "disabled"


@pytest.mark.asyncio
async def test_internal_cron_enforces_vercel_minimum_interval(monkeypatch):
    monkeypatch.setattr(internal.settings, "CRON_SECRET", "expected-secret")
    monkeypatch.setattr(
        internal.settings,
        "TOKEN_AUTO_MAINTENANCE_ENABLED",
        True,
    )
    monkeypatch.setattr(internal.settings, "TOKEN_AUTO_REMOVE_DUPLICATES", True)
    monkeypatch.setattr(internal.settings, "TOKEN_AUTO_HEALTH_CHECK", False)
    monkeypatch.setattr(internal.settings, "TOKEN_AUTO_DELETE_INVALID", False)
    monkeypatch.setattr(
        internal.settings,
        "TOKEN_AUTO_MAINTENANCE_INTERVAL",
        60,
    )
    monkeypatch.setattr(
        type(internal.settings),
        "is_vercel",
        property(lambda self: True),
    )

    captured: dict[str, object] = {}

    async def fake_acquire_runtime_job(
        job_name: str,
        minimum_interval_seconds: int,
        *,
        status: str = "running",
        message: str = "",
    ) -> bool:
        captured["job_name"] = job_name
        captured["minimum_interval_seconds"] = minimum_interval_seconds
        captured["status"] = status
        captured["message"] = message
        return False

    monkeypatch.setattr(internal, "acquire_runtime_job", fake_acquire_runtime_job)

    response = await internal.run_scheduled_token_maintenance(
        authorization="Bearer expected-secret"
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert captured["job_name"] == "token_maintenance"
    assert captured["minimum_interval_seconds"] == 300
    assert payload["status"] == "skipped"


@pytest.mark.asyncio
async def test_internal_cron_updates_job_status_on_success(monkeypatch):
    monkeypatch.setattr(internal.settings, "CRON_SECRET", "expected-secret")
    monkeypatch.setattr(
        internal.settings,
        "TOKEN_AUTO_MAINTENANCE_ENABLED",
        True,
    )
    monkeypatch.setattr(internal.settings, "TOKEN_AUTO_REMOVE_DUPLICATES", True)
    monkeypatch.setattr(internal.settings, "TOKEN_AUTO_HEALTH_CHECK", True)
    monkeypatch.setattr(internal.settings, "TOKEN_AUTO_DELETE_INVALID", True)
    monkeypatch.setattr(
        type(internal.settings),
        "is_vercel",
        property(lambda self: False),
    )

    job_updates: list[tuple[str, str, str]] = []

    class FakeRuntimeConfigDAO:
        async def update_job_run(self, job_name: str, *, status: str, message: str):
            job_updates.append((job_name, status, message))

    async def fake_acquire_runtime_job(*args, **kwargs) -> bool:
        return True

    async def fake_run_token_maintenance(**kwargs):
        assert kwargs["provider"] == "zai"
        assert kwargs["remove_duplicates"] is True
        assert kwargs["run_health_check"] is True
        assert kwargs["delete_invalid_tokens"] is True
        return TokenMaintenanceSummary(
            provider="zai",
            checked_count=4,
            duplicate_removed_count=1,
            valid_count=2,
            guest_count=1,
            invalid_count=1,
            deleted_invalid_count=1,
        )

    monkeypatch.setattr(internal, "acquire_runtime_job", fake_acquire_runtime_job)
    monkeypatch.setattr(internal, "run_token_maintenance", fake_run_token_maintenance)
    monkeypatch.setattr(
        internal,
        "get_runtime_config_dao",
        lambda: FakeRuntimeConfigDAO(),
    )

    response = await internal.run_scheduled_token_maintenance(
        authorization="Bearer expected-secret"
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status_code == 200
    assert payload["status"] == "success"
    assert payload["summary"]["checked_count"] == 4
    assert job_updates == [
        (
            "token_maintenance",
            "success",
            "dedupe=1, checked=4, deleted=1",
        )
    ]
