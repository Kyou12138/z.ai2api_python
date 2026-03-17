from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.admin import auth


def _make_request_with_cookie(session_token: str | None) -> Request:
    cookie_header = (
        f"admin_session={session_token}".encode("utf-8")
        if session_token
        else b""
    )

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/admin",
        "raw_path": b"/admin",
        "query_string": b"",
        "headers": [(b"cookie", cookie_header)] if session_token else [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


def test_create_session_requires_correct_password(monkeypatch):
    monkeypatch.setattr(auth.settings, "ADMIN_PASSWORD", "secret-password")
    monkeypatch.setattr(auth.settings, "SESSION_SECRET_KEY", "session-secret")

    token = auth.create_session("secret-password")

    assert token is not None
    assert auth.verify_session(token) is True
    assert auth.create_session("wrong-password") is None


def test_verify_session_rejects_tampered_cookie(monkeypatch):
    monkeypatch.setattr(auth.settings, "ADMIN_PASSWORD", "secret-password")
    monkeypatch.setattr(auth.settings, "SESSION_SECRET_KEY", "session-secret")

    token = auth.create_session("secret-password")
    assert token is not None

    payload, signature = token.rsplit(".", 1)
    tampered = f"{payload}.deadbeef{signature[8:]}"

    assert auth.verify_session(tampered) is False


@pytest.mark.asyncio
async def test_require_auth_rejects_expired_cookie(monkeypatch):
    class FrozenDateTime(datetime):
        current = datetime(2026, 3, 18, 0, 0, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current.replace(tzinfo=None)
            return cls.current.astimezone(tz)

    monkeypatch.setattr(auth, "datetime", FrozenDateTime)
    monkeypatch.setattr(auth.settings, "ADMIN_PASSWORD", "secret-password")
    monkeypatch.setattr(auth.settings, "SESSION_SECRET_KEY", "session-secret")

    token = auth.create_session("secret-password")
    assert token is not None
    assert auth.get_authenticated_user(_make_request_with_cookie(token)) is True

    FrozenDateTime.current += timedelta(hours=25)

    with pytest.raises(HTTPException) as exc_info:
        await auth.require_auth(_make_request_with_cookie(token))

    assert exc_info.value.status_code == 303
