"""运行环境与数据库后端辅助函数。"""

from __future__ import annotations

import os
from typing import Optional


def is_vercel_environment() -> bool:
    """判断当前是否运行在 Vercel 环境。"""
    return os.getenv("VERCEL") == "1" or bool(os.getenv("VERCEL_ENV"))


def normalize_database_url(database_url: Optional[str]) -> Optional[str]:
    """规范化数据库连接串，兼容 postgres:// 前缀。"""
    if not database_url:
        return None

    normalized = str(database_url).strip()
    if normalized.startswith("postgres://"):
        return "postgresql://" + normalized[len("postgres://") :]
    return normalized


def is_postgres_url(database_url: Optional[str]) -> bool:
    """判断连接串是否指向 PostgreSQL。"""
    normalized = normalize_database_url(database_url)
    if not normalized:
        return False
    return normalized.startswith("postgresql://")


def build_sqlite_url(db_path: str) -> str:
    """将 SQLite 路径转换为统一的数据库 URL。"""
    path = str(db_path or "tokens.db").strip() or "tokens.db"
    if path.startswith("sqlite:///"):
        return path
    return f"sqlite:///{path}"
