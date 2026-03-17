#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from typing import Any, Mapping, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.runtime_env import (
    build_sqlite_url,
    is_postgres_url,
    is_vercel_environment,
    normalize_database_url,
)


RUNTIME_MANAGED_KEYS = (
    "API_ENDPOINT",
    "SKIP_AUTH_TOKEN",
    "TOOL_SUPPORT",
    "SCAN_LIMIT",
    "TOKEN_FAILURE_THRESHOLD",
    "TOKEN_RECOVERY_TIMEOUT",
    "TOKEN_AUTO_MAINTENANCE_ENABLED",
    "TOKEN_AUTO_MAINTENANCE_INTERVAL",
    "TOKEN_AUTO_REMOVE_DUPLICATES",
    "TOKEN_AUTO_HEALTH_CHECK",
    "TOKEN_AUTO_DELETE_INVALID",
    "ANONYMOUS_MODE",
    "GUEST_POOL_SIZE",
    "GLM45_MODEL",
    "GLM45_THINKING_MODEL",
    "GLM45_SEARCH_MODEL",
    "GLM45_AIR_MODEL",
    "GLM46V_MODEL",
    "GLM5_MODEL",
    "GLM47_MODEL",
    "GLM47_THINKING_MODEL",
    "GLM47_SEARCH_MODEL",
    "GLM47_ADVANCED_SEARCH_MODEL",
)

ENV_MANAGED_KEYS = (
    "AUTH_TOKEN",
    "DATABASE_URL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "SOCKS5_PROXY",
    "ADMIN_PASSWORD",
    "SESSION_SECRET_KEY",
    "CRON_SECRET",
    "LISTEN_PORT",
    "SERVICE_NAME",
    "ROOT_PATH",
    "DEBUG_LOGGING",
    "DB_PATH",
    "TOKEN_AUTO_IMPORT_ENABLED",
    "TOKEN_AUTO_IMPORT_SOURCE_DIR",
    "TOKEN_AUTO_IMPORT_INTERVAL",
)

_runtime_setting_overrides: dict[str, str] = {}


class Settings(BaseSettings):
    """Application settings"""

    # API Configuration
    API_ENDPOINT: str = "https://chat.z.ai/api/v2/chat/completions"
    
    # Authentication
    AUTH_TOKEN: Optional[str] = os.getenv("AUTH_TOKEN")
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    CRON_SECRET: Optional[str] = os.getenv("CRON_SECRET")

    # Token池配置
    TOKEN_FAILURE_THRESHOLD: int = int(
        os.getenv("TOKEN_FAILURE_THRESHOLD", "3")
    )
    TOKEN_RECOVERY_TIMEOUT: int = int(
        os.getenv("TOKEN_RECOVERY_TIMEOUT", "1800")
    )
    TOKEN_AUTO_IMPORT_ENABLED: bool = (
        os.getenv("TOKEN_AUTO_IMPORT_ENABLED", "false").lower() == "true"
    )
    TOKEN_AUTO_IMPORT_SOURCE_DIR: str = os.getenv("TOKEN_AUTO_IMPORT_SOURCE_DIR", "")
    TOKEN_AUTO_IMPORT_INTERVAL: int = int(
        os.getenv("TOKEN_AUTO_IMPORT_INTERVAL", "300")
    )
    TOKEN_AUTO_MAINTENANCE_ENABLED: bool = (
        os.getenv("TOKEN_AUTO_MAINTENANCE_ENABLED", "false").lower() == "true"
    )
    TOKEN_AUTO_MAINTENANCE_INTERVAL: int = int(
        os.getenv("TOKEN_AUTO_MAINTENANCE_INTERVAL", "1800")
    )
    TOKEN_AUTO_REMOVE_DUPLICATES: bool = (
        os.getenv("TOKEN_AUTO_REMOVE_DUPLICATES", "true").lower() == "true"
    )
    TOKEN_AUTO_HEALTH_CHECK: bool = (
        os.getenv("TOKEN_AUTO_HEALTH_CHECK", "true").lower() == "true"
    )
    TOKEN_AUTO_DELETE_INVALID: bool = (
        os.getenv("TOKEN_AUTO_DELETE_INVALID", "false").lower() == "true"
    )

    # Model Configuration
    GLM45_MODEL: str = os.getenv("GLM45_MODEL", "GLM-4.5")
    GLM45_THINKING_MODEL: str = os.getenv("GLM45_THINKING_MODEL", "GLM-4.5-Thinking")
    GLM45_SEARCH_MODEL: str = os.getenv("GLM45_SEARCH_MODEL", "GLM-4.5-Search")
    GLM45_AIR_MODEL: str = os.getenv("GLM45_AIR_MODEL", "GLM-4.5-Air")
    GLM46V_MODEL: str = os.getenv("GLM46V_MODEL", "GLM-4.6V")
    GLM5_MODEL: str = os.getenv("GLM5_MODEL", "GLM-5")
    GLM47_MODEL: str = os.getenv("GLM47_MODEL", "GLM-4.7")
    GLM47_THINKING_MODEL: str = os.getenv("GLM47_THINKING_MODEL", "GLM-4.7-Thinking")
    GLM47_SEARCH_MODEL: str = os.getenv("GLM47_SEARCH_MODEL", "GLM-4.7-Search")
    GLM47_ADVANCED_SEARCH_MODEL: str = os.getenv(
        "GLM47_ADVANCED_SEARCH_MODEL",
        "GLM-4.7-advanced-search",
    )

    # Server Configuration
    LISTEN_PORT: int = int(os.getenv("LISTEN_PORT", "8080"))
    DEBUG_LOGGING: bool = os.getenv("DEBUG_LOGGING", "true").lower() == "true"
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "api-proxy-server")
    ROOT_PATH: str = os.getenv("ROOT_PATH", "")

    ANONYMOUS_MODE: bool = os.getenv("ANONYMOUS_MODE", "true").lower() == "true"
    GUEST_POOL_SIZE: int = int(os.getenv("GUEST_POOL_SIZE", "3"))
    TOOL_SUPPORT: bool = os.getenv("TOOL_SUPPORT", "true").lower() == "true"
    SCAN_LIMIT: int = int(os.getenv("SCAN_LIMIT", "200000"))
    SKIP_AUTH_TOKEN: bool = os.getenv("SKIP_AUTH_TOKEN", "false").lower() == "true"

    # Proxy Configuration
    HTTP_PROXY: Optional[str] = os.getenv("HTTP_PROXY")
    HTTPS_PROXY: Optional[str] = os.getenv("HTTPS_PROXY")
    SOCKS5_PROXY: Optional[str] = os.getenv("SOCKS5_PROXY")

    # Admin Panel Authentication
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
    SESSION_SECRET_KEY: str = os.getenv(
        "SESSION_SECRET_KEY",
        "your-secret-key-change-in-production",
    )
    DB_PATH: str = os.getenv("DB_PATH", "tokens.db")

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",  # 忽略额外字段，防止环境变量中的未知字段导致验证错误
    )

    @property
    def is_vercel(self) -> bool:
        """是否运行在 Vercel。"""
        return is_vercel_environment()

    @property
    def normalized_database_url(self) -> str:
        """返回规范化后的数据库连接串。"""
        return normalize_database_url(self.DATABASE_URL) or build_sqlite_url(
            self.DB_PATH
        )

    @property
    def uses_postgres(self) -> bool:
        """当前是否使用 PostgreSQL。"""
        return is_postgres_url(self.normalized_database_url)

    @property
    def allow_file_logging(self) -> bool:
        """Vercel 环境下禁用文件日志。"""
        return not self.is_vercel

    @property
    def is_serverless(self) -> bool:
        """当前是否处于无状态 Serverless 运行模式。"""
        return self.is_vercel


settings = Settings()


def get_runtime_setting_overrides() -> dict[str, str]:
    """获取当前已加载的运行时配置覆盖项。"""
    return dict(_runtime_setting_overrides)


def coerce_setting_value(key: str, value: Any) -> Any:
    """按 Settings 字段类型转换运行时配置值。"""
    field = settings.model_fields[key]
    annotation = field.annotation

    if annotation is bool:
        return str(value).strip().lower() == "true"
    if annotation is int:
        return int(value)
    return "" if value is None else str(value)


def _copy_settings_values(target: Settings, source: Settings) -> None:
    for field_name in source.model_fields.keys():
        setattr(target, field_name, getattr(source, field_name))


def reload_settings_from_env() -> Settings:
    """仅从环境变量重新加载配置。"""
    new_settings = type(settings)()
    _copy_settings_values(settings, new_settings)
    return settings


def apply_runtime_setting_overrides(
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """将数据库中的运行时配置覆盖到全局 settings。"""
    global _runtime_setting_overrides

    effective_overrides = {
        key: str(value)
        for key, value in (overrides or {}).items()
        if key in RUNTIME_MANAGED_KEYS
    }
    _runtime_setting_overrides = effective_overrides

    for key, raw_value in effective_overrides.items():
        setattr(settings, key, coerce_setting_value(key, raw_value))

    return get_runtime_setting_overrides()


async def reload_settings_from_sources() -> dict[str, str]:
    """重新加载环境变量，并应用数据库中的运行时配置覆盖。"""
    reload_settings_from_env()
    runtime_overrides: dict[str, str] = {}

    try:
        from app.services.runtime_config_dao import get_runtime_config_dao

        dao = get_runtime_config_dao()
        await dao.init_storage()
        runtime_overrides = await dao.get_settings(RUNTIME_MANAGED_KEYS)
    except Exception:
        runtime_overrides = {}

    apply_runtime_setting_overrides(runtime_overrides)
    return runtime_overrides
