"""运行时配置与定时任务状态存储。"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional

import aiosqlite

from app.core.config import settings
from app.core.runtime_env import is_postgres_url
from app.services.postgres_backend import get_postgres_pool
from app.utils.logger import logger

SQLITE_RUNTIME_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS runtime_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_runs (
    job_name TEXT PRIMARY KEY,
    last_run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'idle',
    message TEXT DEFAULT ''
);
"""

POSTGRES_RUNTIME_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS runtime_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_runs (
    job_name TEXT PRIMARY KEY,
    last_run_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'idle',
    message TEXT DEFAULT ''
);
"""


class RuntimeConfigDAO:
    """SQLite 版运行时配置存储。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or settings.DB_PATH
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        db_dir = Path(self.db_path).expanduser().resolve().parent
        if str(db_dir) not in {".", ""}:
            db_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def get_connection(self):
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def init_storage(self) -> None:
        async with self.get_connection() as conn:
            await conn.executescript(SQLITE_RUNTIME_CONFIG_SQL)
            await conn.commit()

    async def get_settings(
        self,
        keys: Iterable[str] | None = None,
    ) -> dict[str, str]:
        await self.init_storage()
        async with self.get_connection() as conn:
            if keys:
                key_list = list(keys)
                if not key_list:
                    return {}
                placeholders = ",".join("?" for _ in key_list)
                query = (
                    "SELECT key, value FROM runtime_settings "
                    f"WHERE key IN ({placeholders})"
                )
                cursor = await conn.execute(
                    query,
                    key_list,
                )
            else:
                cursor = await conn.execute(
                    "SELECT key, value FROM runtime_settings"
                )
            rows = await cursor.fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    async def upsert_settings(self, updates: Mapping[str, object]) -> None:
        if not updates:
            return
        await self.init_storage()
        async with self.get_connection() as conn:
            for key, value in updates.items():
                await conn.execute(
                    """
                    INSERT INTO runtime_settings (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, str(value)),
                )
            await conn.commit()

    async def acquire_job(
        self,
        job_name: str,
        minimum_interval_seconds: int,
        *,
        status: str = "running",
        message: str = "",
    ) -> bool:
        await self.init_storage()
        lock = sqlite3.connect(self.db_path)
        lock.row_factory = sqlite3.Row
        try:
            lock.execute("BEGIN IMMEDIATE")
            row = lock.execute(
                "SELECT last_run_at FROM job_runs WHERE job_name = ?",
                (job_name,),
            ).fetchone()
            if row is not None:
                last_run_at = datetime.strptime(
                    str(row["last_run_at"]),
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - last_run_at
                if delta.total_seconds() < minimum_interval_seconds:
                    lock.rollback()
                    return False

            lock.execute(
                """
                INSERT INTO job_runs (job_name, last_run_at, status, message)
                VALUES (?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    last_run_at = CURRENT_TIMESTAMP,
                    status = excluded.status,
                    message = excluded.message
                """,
                (job_name, status, message),
            )
            lock.commit()
            return True
        finally:
            lock.close()

    async def update_job_run(
        self,
        job_name: str,
        *,
        status: str,
        message: str = "",
    ) -> None:
        await self.init_storage()
        async with self.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO job_runs (job_name, last_run_at, status, message)
                VALUES (?, CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(job_name) DO UPDATE SET
                    last_run_at = CURRENT_TIMESTAMP,
                    status = excluded.status,
                    message = excluded.message
                """,
                (job_name, status, message),
            )
            await conn.commit()

    async def get_job_run(self, job_name: str) -> Optional[dict[str, str]]:
        await self.init_storage()
        async with self.get_connection() as conn:
            query = (
                "SELECT job_name, last_run_at, status, message "
                "FROM job_runs WHERE job_name = ?"
            )
            cursor = await conn.execute(
                query,
                (job_name,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None


class PostgresRuntimeConfigDAO:
    """PostgreSQL 版运行时配置存储。"""

    async def init_storage(self) -> None:
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(POSTGRES_RUNTIME_CONFIG_SQL)

    async def get_settings(
        self,
        keys: Iterable[str] | None = None,
    ) -> dict[str, str]:
        await self.init_storage()
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            if keys:
                key_list = list(keys)
                if not key_list:
                    return {}
                rows = await conn.fetch(
                    """
                    SELECT key, value
                    FROM runtime_settings
                    WHERE key = ANY($1::text[])
                    """,
                    key_list,
                )
            else:
                rows = await conn.fetch("SELECT key, value FROM runtime_settings")
        return {str(row["key"]): str(row["value"]) for row in rows}

    async def upsert_settings(self, updates: Mapping[str, object]) -> None:
        if not updates:
            return
        await self.init_storage()
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                for key, value in updates.items():
                    await conn.execute(
                        """
                        INSERT INTO runtime_settings (key, value, updated_at)
                        VALUES ($1, $2, CURRENT_TIMESTAMP)
                        ON CONFLICT(key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        key,
                        str(value),
                    )

    async def acquire_job(
        self,
        job_name: str,
        minimum_interval_seconds: int,
        *,
        status: str = "running",
        message: str = "",
    ) -> bool:
        await self.init_storage()
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO job_runs (job_name, last_run_at, status, message)
                VALUES ($1, CURRENT_TIMESTAMP, $2, $3)
                ON CONFLICT (job_name) DO UPDATE SET
                    last_run_at = CURRENT_TIMESTAMP,
                    status = EXCLUDED.status,
                    message = EXCLUDED.message
                WHERE job_runs.last_run_at <= (
                    CURRENT_TIMESTAMP - make_interval(secs => $4::int)
                )
                RETURNING job_name
                """,
                job_name,
                status,
                message,
                max(0, int(minimum_interval_seconds)),
            )
        return row is not None

    async def update_job_run(
        self,
        job_name: str,
        *,
        status: str,
        message: str = "",
    ) -> None:
        await self.init_storage()
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO job_runs (job_name, last_run_at, status, message)
                VALUES ($1, CURRENT_TIMESTAMP, $2, $3)
                ON CONFLICT (job_name) DO UPDATE SET
                    last_run_at = CURRENT_TIMESTAMP,
                    status = EXCLUDED.status,
                    message = EXCLUDED.message
                """,
                job_name,
                status,
                message,
            )

    async def get_job_run(self, job_name: str) -> Optional[dict[str, str]]:
        await self.init_storage()
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT job_name, last_run_at, status, message
                FROM job_runs
                WHERE job_name = $1
                """,
                job_name,
            )
        return dict(row) if row else None


_runtime_config_dao: Optional[object] = None
_runtime_config_lock = asyncio.Lock()


def _build_runtime_config_dao():
    if is_postgres_url(settings.normalized_database_url):
        return PostgresRuntimeConfigDAO()
    return RuntimeConfigDAO(settings.DB_PATH)


def get_runtime_config_dao():
    global _runtime_config_dao
    if _runtime_config_dao is None:
        _runtime_config_dao = _build_runtime_config_dao()
    return _runtime_config_dao


async def init_runtime_config_storage() -> None:
    dao = get_runtime_config_dao()
    await dao.init_storage()


async def acquire_runtime_job(
    job_name: str,
    minimum_interval_seconds: int,
    *,
    status: str = "running",
    message: str = "",
) -> bool:
    dao = get_runtime_config_dao()
    acquired = await dao.acquire_job(
        job_name,
        minimum_interval_seconds,
        status=status,
        message=message,
    )
    if not acquired:
        logger.info(f"⏭️ 跳过任务 {job_name}：未达到最小执行间隔")
    return acquired
