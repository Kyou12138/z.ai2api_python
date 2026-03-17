"""PostgreSQL 连接池辅助函数。"""

from __future__ import annotations

import asyncio
from typing import Optional

import asyncpg

from app.core.config import settings
from app.core.runtime_env import normalize_database_url

_pool: Optional[asyncpg.Pool] = None
_pool_lock = asyncio.Lock()


async def get_postgres_pool() -> asyncpg.Pool:
    """获取全局 PostgreSQL 连接池。"""
    global _pool
    if _pool is not None:
        return _pool

    async with _pool_lock:
        if _pool is None:
            database_url = normalize_database_url(settings.DATABASE_URL)
            if not database_url:
                raise RuntimeError("未配置 PostgreSQL DATABASE_URL")

            _pool = await asyncpg.create_pool(
                dsn=database_url,
                min_size=1,
                max_size=5,
                timeout=30,
                command_timeout=30,
            )

    return _pool


async def close_postgres_pool() -> None:
    """关闭全局 PostgreSQL 连接池。"""
    global _pool
    async with _pool_lock:
        pool = _pool
        _pool = None

    if pool is not None:
        await pool.close()
