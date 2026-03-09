"""数据库适配层，统一 SQLite / PostgreSQL 的连接与结果格式。"""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterable, Iterator, Optional, Sequence

import aiosqlite

from app.core.config import settings

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - 仅在未安装 psycopg 时触发
    psycopg = None
    dict_row = None


def normalize_db_type(db_type: Optional[str]) -> str:
    """统一数据库类型别名。"""
    value = (db_type or "sqlite").strip().lower()
    if value in {"postgres", "postgresql", "pgsql", "pg"}:
        return "postgresql"
    return "sqlite"


class DBRow(dict):
    """兼容字典和索引访问的行对象。"""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _convert_row(row: Any) -> Optional[DBRow]:
    """将驱动返回的行对象标准化为可索引字典。"""
    if row is None:
        return None
    if isinstance(row, DBRow):
        return row
    if isinstance(row, dict):
        return DBRow(row)
    if isinstance(row, sqlite3.Row):
        return DBRow({key: row[key] for key in row.keys()})
    if isinstance(row, tuple):
        return DBRow({str(index): value for index, value in enumerate(row)})
    return DBRow(dict(row))


class AsyncDatabaseCursor:
    """统一的异步游标封装。"""

    def __init__(self, raw_cursor: Any, *, lastrowid: Optional[int] = None):
        self._raw_cursor = raw_cursor
        self._lastrowid = lastrowid

    @property
    def lastrowid(self) -> Optional[int]:
        return self._lastrowid if self._lastrowid is not None else getattr(
            self._raw_cursor, "lastrowid", None
        )

    @property
    def rowcount(self) -> int:
        return getattr(self._raw_cursor, "rowcount", -1)

    async def fetchone(self) -> Optional[DBRow]:
        row = await self._raw_cursor.fetchone()
        return _convert_row(row)

    async def fetchall(self) -> list[DBRow]:
        rows = await self._raw_cursor.fetchall()
        return [_convert_row(row) for row in rows]


class AsyncDatabaseConnection:
    """统一的异步连接封装。"""

    def __init__(self, backend: "DatabaseBackend", raw_connection: Any):
        self.backend = backend
        self._raw_connection = raw_connection

    async def execute(
        self,
        query: str,
        params: Optional[Sequence[Any]] = None,
        *,
        lastrowid: Optional[int] = None,
    ) -> AsyncDatabaseCursor:
        normalized_query = self.backend.format_query(query)
        normalized_params = tuple(params or ())

        if self.backend.is_sqlite:
            cursor = await self._raw_connection.execute(
                normalized_query,
                normalized_params,
            )
            return AsyncDatabaseCursor(cursor, lastrowid=lastrowid)

        cursor = self._raw_connection.cursor(row_factory=dict_row)
        await cursor.execute(normalized_query, normalized_params)
        return AsyncDatabaseCursor(cursor, lastrowid=lastrowid)

    async def commit(self) -> None:
        await self._raw_connection.commit()


class DatabaseBackend:
    """数据库后端描述与连接工厂。"""

    def __init__(self) -> None:
        self.db_type = normalize_db_type(
            settings.DB_TYPE or (
                "postgresql"
                if (settings.DATABASE_URL or "").startswith(("postgres://", "postgresql://"))
                else "sqlite"
            )
        )
        self.database_url = settings.DATABASE_URL or None
        self.db_path = settings.DB_PATH

    @property
    def is_sqlite(self) -> bool:
        return self.db_type == "sqlite"

    @property
    def is_postgresql(self) -> bool:
        return self.db_type == "postgresql"

    def _require_psycopg(self) -> Any:
        if psycopg is None:
            raise RuntimeError(
                "当前环境未安装 psycopg，请执行 `pip install psycopg[binary]` 后再使用 PostgreSQL。"
            )
        return psycopg

    def _ensure_sqlite_directory(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    def validate(self) -> None:
        """校验当前数据库配置。"""
        if self.is_sqlite:
            self._ensure_sqlite_directory()
            return

        if not self.database_url:
            raise RuntimeError("已启用 PostgreSQL，但未配置 DATABASE_URL。")
        self._require_psycopg()

    def format_query(self, query: str) -> str:
        """将统一的问号占位符转换为目标驱动支持的格式。"""
        if self.is_postgresql:
            return query.replace("?", "%s")
        return query

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncDatabaseConnection]:
        """获取异步数据库连接。"""
        self.validate()

        if self.is_sqlite:
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield AsyncDatabaseConnection(self, conn)
            finally:
                await conn.close()
            return

        psycopg_module = self._require_psycopg()
        conn = await psycopg_module.AsyncConnection.connect(self.database_url)
        try:
            yield AsyncDatabaseConnection(self, conn)
        finally:
            await conn.close()

    @contextmanager
    def sync_connection(self) -> Iterator[Any]:
        """获取同步数据库连接，用于建表和轻量迁移。"""
        self.validate()

        if self.is_sqlite:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
            finally:
                conn.close()
            return

        psycopg_module = self._require_psycopg()
        conn = psycopg_module.connect(self.database_url)
        try:
            yield conn
        finally:
            conn.close()

    def execute_statements_sync(self, statements: Iterable[str]) -> None:
        """同步执行多条 SQL 语句。"""
        statements = [statement.strip() for statement in statements if statement.strip()]
        if not statements:
            return

        with self.sync_connection() as conn:
            if self.is_sqlite:
                conn.executescript(";\n".join(statements) + ";")
            else:
                with conn.cursor() as cursor:
                    for statement in statements:
                        cursor.execute(self.format_query(statement))
            conn.commit()


_database_backend: Optional[DatabaseBackend] = None


def get_database_backend() -> DatabaseBackend:
    """获取数据库后端单例。"""
    global _database_backend
    if _database_backend is None:
        _database_backend = DatabaseBackend()
    return _database_backend


def reset_database_backend() -> None:
    """重置数据库后端单例。"""
    global _database_backend
    _database_backend = None
