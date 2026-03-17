#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""将旧 SQLite Token 数据迁移到当前配置的数据库。"""

from __future__ import annotations

import asyncio
import sys

import aiosqlite

from app.core.config import settings
from app.services.token_dao import get_token_dao


async def migrate(sqlite_path: str) -> int:
    if not settings.uses_postgres:
        raise RuntimeError("当前未配置 PostgreSQL DATABASE_URL，无法执行迁移。")

    target_dao = get_token_dao()
    await target_dao.init_database()

    migrated = 0
    async with aiosqlite.connect(sqlite_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT provider, token, token_type, priority, is_enabled
            FROM tokens
            ORDER BY id ASC
            """
        )
        rows = await cursor.fetchall()

        for row in rows:
            token_id = await target_dao.add_token(
                provider=str(row["provider"]),
                token=str(row["token"]),
                token_type=str(row["token_type"] or "user"),
                priority=int(row["priority"] or 0),
                validate=False,
            )
            if token_id is None:
                continue

            if not bool(row["is_enabled"]):
                await target_dao.update_token_status(token_id, False)
            migrated += 1

    return migrated


async def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: uv run python migrate_sqlite_to_database.py <sqlite_db_path>")
        return 1

    migrated = await migrate(argv[1])
    print(f"迁移完成，共写入 {migrated} 条 Token 记录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
