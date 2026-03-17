"""管理后台认证中间件。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request, status

from app.core.config import settings

SESSION_EXPIRE_HOURS = 24


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _urlsafe_b64decode(raw: str) -> bytes:
    text = str(raw or "")
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("utf-8"))


def generate_session_token(password: str) -> Optional[str]:
    """生成签名 Session Token。"""
    if password != settings.ADMIN_PASSWORD:
        return None

    expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_EXPIRE_HOURS)
    payload = {
        "authenticated": True,
        "exp": int(expires_at.timestamp()),
    }
    payload_raw = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_token = _urlsafe_b64encode(payload_raw)
    signature = hmac.new(
        settings.SESSION_SECRET_KEY.encode("utf-8"),
        payload_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_token}.{signature}"


def create_session(password: str) -> Optional[str]:
    """创建签名 Cookie。"""
    return generate_session_token(password)


def verify_session(session_token: Optional[str]) -> bool:
    """验证签名 Cookie。"""
    if not session_token or "." not in str(session_token):
        return False

    payload_token, provided_signature = str(session_token).rsplit(".", 1)
    expected_signature = hmac.new(
        settings.SESSION_SECRET_KEY.encode("utf-8"),
        payload_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided_signature, expected_signature):
        return False

    try:
        payload = json.loads(_urlsafe_b64decode(payload_token).decode("utf-8"))
    except Exception:
        return False

    if not payload.get("authenticated"):
        return False

    expires_at = int(payload.get("exp") or 0)
    return datetime.now(timezone.utc).timestamp() <= expires_at


def delete_session(session_token: Optional[str]):
    """无状态 Cookie 模式下由客户端删除 Cookie 即可。"""
    return None


def get_session_token_from_request(request: Request) -> Optional[str]:
    """从请求中获取 Session Token。"""
    return request.cookies.get("admin_session")


async def require_auth(request: Request):
    """要求用户已登录。"""
    session_token = get_session_token_from_request(request)
    if not verify_session(session_token):
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="未登录",
            headers={"Location": "/admin/login"},
        )


def get_authenticated_user(request: Request) -> bool:
    """获取当前请求是否已认证。"""
    session_token = get_session_token_from_request(request)
    return verify_session(session_token)


def cleanup_expired_sessions():
    """兼容旧接口：无状态 Cookie 模式无需后台清理。"""
    return 0
