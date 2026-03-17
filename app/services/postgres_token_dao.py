"""PostgreSQL 版 Token DAO。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.postgres_backend import get_postgres_pool
from app.utils.logger import logger

POSTGRES_TOKEN_SQL = """
CREATE TABLE IF NOT EXISTS tokens (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    token TEXT NOT NULL,
    token_type TEXT DEFAULT 'user',
    is_enabled BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, token)
);

CREATE TABLE IF NOT EXISTS token_stats (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    total_requests INTEGER DEFAULT 0,
    successful_requests INTEGER DEFAULT 0,
    failed_requests INTEGER DEFAULT 0,
    last_success_time TIMESTAMPTZ,
    last_failure_time TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tokens_provider ON tokens(provider);
CREATE INDEX IF NOT EXISTS idx_tokens_enabled ON tokens(is_enabled);
CREATE INDEX IF NOT EXISTS idx_token_stats_token_id ON token_stats(token_id);
"""


class PostgresTokenDAO:
    """PostgreSQL 数据访问对象。"""

    async def init_database(self):
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(POSTGRES_TOKEN_SQL)

    async def add_token(
        self,
        provider: str,
        token: str,
        token_type: str = "user",
        priority: int = 0,
        validate: bool = True,
    ) -> Optional[int]:
        try:
            if provider == "zai" and validate:
                from app.utils.token_pool import ZAITokenValidator

                validated_type, is_valid, error_msg = (
                    await ZAITokenValidator.validate_token(token)
                )
                if validated_type == "guest":
                    logger.warning(
                        f"🚫 拒绝添加匿名用户 Token: {token[:20]}... - {error_msg}"
                    )
                    return None
                if not is_valid:
                    logger.warning(f"🚫 Token 验证失败: {token[:20]}... - {error_msg}")
                    return None
                token_type = validated_type

            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO tokens (provider, token, token_type, priority)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT(provider, token) DO NOTHING
                    RETURNING id
                    """,
                    provider,
                    token,
                    token_type,
                    priority,
                )
                if row is None:
                    logger.warning(f"⚠️ Token 已存在: {provider} - {token[:20]}...")
                    return None

                token_id = int(row["id"])
                await conn.execute(
                    "INSERT INTO token_stats (token_id) VALUES ($1)",
                    token_id,
                )
                logger.info(
                    f"✅ 添加 Token: {provider} ({token_type}) - {token[:20]}..."
                )
                return token_id
        except Exception as exc:
            logger.error(f"❌ 添加 Token 失败: {exc}")
            return None

    async def get_tokens_by_provider(
        self,
        provider: str,
        enabled_only: bool = True,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict]:
        try:
            query = """
                SELECT
                    t.*,
                    ts.total_requests,
                    ts.successful_requests,
                    ts.failed_requests,
                    ts.last_success_time,
                    ts.last_failure_time
                FROM tokens t
                LEFT JOIN token_stats ts ON t.id = ts.token_id
                WHERE t.provider = $1
            """
            params: list[object] = [provider]

            if enabled_only:
                query += " AND t.is_enabled = TRUE"

            query += " ORDER BY t.priority DESC, t.id ASC"
            if limit is not None:
                query += " LIMIT $2 OFFSET $3"
                params.extend([limit, max(0, offset)])

            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error(f"❌ 查询 Token 失败: {exc}")
            return []

    async def get_all_tokens(self, enabled_only: bool = False) -> List[Dict]:
        try:
            query = """
                SELECT
                    t.*,
                    ts.total_requests,
                    ts.successful_requests,
                    ts.failed_requests,
                    ts.last_success_time,
                    ts.last_failure_time
                FROM tokens t
                LEFT JOIN token_stats ts ON t.id = ts.token_id
            """
            if enabled_only:
                query += " WHERE t.is_enabled = TRUE"
            query += " ORDER BY t.provider, t.priority DESC, t.id ASC"

            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(query)
            return [dict(row) for row in rows]
        except Exception as exc:
            logger.error(f"❌ 查询所有 Token 失败: {exc}")
            return []

    async def update_token_status(self, token_id: int, is_enabled: bool):
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE tokens
                    SET is_enabled = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $2
                    """,
                    is_enabled,
                    token_id,
                )
            logger.info(f"✅ 更新 Token 状态: id={token_id}, enabled={is_enabled}")
        except Exception as exc:
            logger.error(f"❌ 更新 Token 状态失败: {exc}")

    async def update_token_type(self, token_id: int, token_type: str):
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE tokens
                    SET token_type = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = $2
                    """,
                    token_type,
                    token_id,
                )
            logger.info(f"✅ 更新 Token 类型: id={token_id}, type={token_type}")
        except Exception as exc:
            logger.error(f"❌ 更新 Token 类型失败: {exc}")

    async def delete_token(self, token_id: int):
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM tokens WHERE id = $1", token_id)
            logger.info(f"✅ 删除 Token: id={token_id}")
        except Exception as exc:
            logger.error(f"❌ 删除 Token 失败: {exc}")

    async def delete_tokens_by_ids(self, token_ids: List[int]) -> int:
        if not token_ids:
            return 0
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "DELETE FROM tokens WHERE id = ANY($1::bigint[]) RETURNING id",
                    token_ids,
                )
            deleted_count = len(rows)
            logger.info(f"✅ 批量删除 Token: {deleted_count} 个")
            return deleted_count
        except Exception as exc:
            logger.error(f"❌ 批量删除 Token 失败: {exc}")
            return 0

    async def delete_tokens_by_provider(self, provider: str):
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM tokens WHERE provider = $1",
                    provider,
                )
            logger.info(f"✅ 删除提供商所有 Token: {provider}")
        except Exception as exc:
            logger.error(f"❌ 删除提供商 Token 失败: {exc}")

    async def record_success(self, token_id: int):
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE token_stats
                    SET total_requests = total_requests + 1,
                        successful_requests = successful_requests + 1,
                        last_success_time = CURRENT_TIMESTAMP
                    WHERE token_id = $1
                    """,
                    token_id,
                )
        except Exception as exc:
            logger.error(f"❌ 记录成功失败: {exc}")

    async def record_failure(self, token_id: int):
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE token_stats
                    SET total_requests = total_requests + 1,
                        failed_requests = failed_requests + 1,
                        last_failure_time = CURRENT_TIMESTAMP
                    WHERE token_id = $1
                    """,
                    token_id,
                )
        except Exception as exc:
            logger.error(f"❌ 记录失败失败: {exc}")

    async def get_token_stats(self, token_id: int) -> Optional[Dict]:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM token_stats WHERE token_id = $1",
                    token_id,
                )
            return dict(row) if row else None
        except Exception as exc:
            logger.error(f"❌ 获取统计信息失败: {exc}")
            return None

    async def bulk_add_tokens(
        self,
        provider: str,
        tokens: List[str],
        token_type: str = "user",
        validate: bool = True,
    ) -> Tuple[int, int]:
        added_count = 0
        failed_count = 0

        for token in tokens:
            if token.strip():
                token_id = await self.add_token(
                    provider,
                    token.strip(),
                    token_type,
                    validate=validate,
                )
                if token_id:
                    added_count += 1
                else:
                    failed_count += 1

        logger.info(
            f"✅ 批量添加完成: {provider} - 成功 {added_count}/{len(tokens)}，失败 {failed_count}"
        )
        return added_count, failed_count

    async def replace_tokens(
        self,
        provider: str,
        tokens: List[str],
        token_type: str = "user",
    ):
        await self.delete_tokens_by_provider(provider)
        added_count, _ = await self.bulk_add_tokens(
            provider,
            tokens,
            token_type,
        )
        logger.info(f"✅ 替换 Token 完成: {provider} - {added_count} 个")
        return added_count

    async def remove_duplicate_tokens(self, provider: Optional[str] = None) -> int:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                if provider:
                    rows = await conn.fetch(
                        """
                        WITH ranked AS (
                            SELECT
                                id,
                                ROW_NUMBER() OVER (
                                    PARTITION BY provider, token
                                    ORDER BY priority DESC, id ASC
                                ) AS row_number
                            FROM tokens
                            WHERE provider = $1
                        )
                        DELETE FROM tokens
                        WHERE id IN (
                            SELECT id FROM ranked WHERE row_number > 1
                        )
                        RETURNING id
                        """,
                        provider,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        WITH ranked AS (
                            SELECT
                                id,
                                ROW_NUMBER() OVER (
                                    PARTITION BY provider, token
                                    ORDER BY priority DESC, id ASC
                                ) AS row_number
                            FROM tokens
                        )
                        DELETE FROM tokens
                        WHERE id IN (
                            SELECT id FROM ranked WHERE row_number > 1
                        )
                        RETURNING id
                        """
                    )

            deleted_count = len(rows)
            if deleted_count > 0:
                logger.info(f"✅ 已清理重复 Token: {deleted_count} 个")
            return deleted_count
        except Exception as exc:
            logger.error(f"❌ 清理重复 Token 失败: {exc}")
            return 0

    async def get_token_by_value(self, provider: str, token: str) -> Optional[Dict]:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        t.*,
                        ts.total_requests,
                        ts.successful_requests,
                        ts.failed_requests
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                    WHERE t.provider = $1 AND t.token = $2
                    """,
                    provider,
                    token,
                )
            return dict(row) if row else None
        except Exception as exc:
            logger.error(f"❌ 查询 Token 失败: {exc}")
            return None

    async def get_provider_stats(self, provider: str) -> Dict:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) AS total_tokens,
                        SUM(CASE WHEN is_enabled = TRUE THEN 1 ELSE 0 END) AS enabled_tokens,
                        COALESCE(SUM(ts.total_requests), 0) AS total_requests,
                        COALESCE(SUM(ts.successful_requests), 0) AS successful_requests,
                        COALESCE(SUM(ts.failed_requests), 0) AS failed_requests
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                    WHERE t.provider = $1
                    """,
                    provider,
                )
            return dict(row) if row else {}
        except Exception as exc:
            logger.error(f"❌ 获取提供商统计失败: {exc}")
            return {}

    async def get_provider_token_counts(self, provider: str) -> Dict[str, int]:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) AS total_tokens,
                        SUM(CASE WHEN is_enabled = TRUE THEN 1 ELSE 0 END) AS enabled_tokens,
                        SUM(CASE WHEN token_type = 'user' THEN 1 ELSE 0 END) AS user_tokens,
                        SUM(CASE WHEN token_type = 'guest' THEN 1 ELSE 0 END) AS guest_tokens,
                        SUM(CASE WHEN token_type = 'unknown' THEN 1 ELSE 0 END) AS unknown_tokens
                    FROM tokens
                    WHERE provider = $1
                    """,
                    provider,
                )
            if not row:
                return {
                    "total_tokens": 0,
                    "enabled_tokens": 0,
                    "user_tokens": 0,
                    "guest_tokens": 0,
                    "unknown_tokens": 0,
                }
            return {
                "total_tokens": int(row["total_tokens"] or 0),
                "enabled_tokens": int(row["enabled_tokens"] or 0),
                "user_tokens": int(row["user_tokens"] or 0),
                "guest_tokens": int(row["guest_tokens"] or 0),
                "unknown_tokens": int(row["unknown_tokens"] or 0),
            }
        except Exception as exc:
            logger.error(f"❌ 获取 Token 数量统计失败: {exc}")
            return {
                "total_tokens": 0,
                "enabled_tokens": 0,
                "user_tokens": 0,
                "guest_tokens": 0,
                "unknown_tokens": 0,
            }

    async def count_tokens_by_provider(
        self,
        provider: str,
        enabled_only: bool = False,
    ) -> int:
        try:
            query = "SELECT COUNT(*) AS total_count FROM tokens WHERE provider = $1"
            params: list[object] = [provider]
            if enabled_only:
                query += " AND is_enabled = TRUE"
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            return int(row["total_count"] or 0) if row else 0
        except Exception as exc:
            logger.error(f"❌ 统计 Token 总数失败: {exc}")
            return 0

    async def get_token_provider(self, token_id: int) -> str:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT provider FROM tokens WHERE id = $1",
                    token_id,
                )
            return str(row["provider"]) if row else "zai"
        except Exception as exc:
            logger.error(f"❌ 查询 Token 提供商失败: {exc}")
            return "zai"

    async def get_token_with_stats(self, token_id: int) -> Optional[Dict]:
        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        t.*,
                        ts.total_requests,
                        ts.successful_requests,
                        ts.failed_requests,
                        ts.last_success_time,
                        ts.last_failure_time
                    FROM tokens t
                    LEFT JOIN token_stats ts ON t.id = ts.token_id
                    WHERE t.id = $1
                    """,
                    token_id,
                )
            return dict(row) if row else None
        except Exception as exc:
            logger.error(f"❌ 查询 Token 详情失败: {exc}")
            return None

    async def validate_and_update_token(self, token_id: int) -> bool:
        try:
            token_record = await self.get_token_with_stats(token_id)
            if not token_record:
                logger.error(f"❌ Token ID {token_id} 不存在")
                return False

            provider = token_record["provider"]
            token = token_record["token"]
            if provider != "zai":
                logger.info(f"⏭️ 跳过非 zai 提供商的 Token 验证: {provider}")
                return True

            from app.utils.token_pool import ZAITokenValidator

            token_type, is_valid, error_msg = await ZAITokenValidator.validate_token(
                token
            )
            await self.update_token_type(token_id, token_type)

            if not is_valid:
                logger.warning(
                    f"⚠️ Token 验证失败: id={token_id}, type={token_type}, error={error_msg}"
                )
            return is_valid
        except Exception as exc:
            logger.error(f"❌ 验证 Token 失败: {exc}")
            return False

    async def validate_tokens_detailed(self, provider: str = "zai") -> Dict[str, Any]:
        try:
            tokens = await self.get_tokens_by_provider(provider, enabled_only=False)
            if not tokens:
                logger.warning(f"⚠️ 没有需要验证的 {provider} Token")
                return {
                    "checked": 0,
                    "valid": 0,
                    "guest": 0,
                    "invalid": 0,
                    "invalid_token_ids": [],
                }

            from app.utils.token_pool import ZAITokenValidator

            stats: Dict[str, Any] = {
                "checked": len(tokens),
                "valid": 0,
                "guest": 0,
                "invalid": 0,
                "invalid_token_ids": [],
            }

            for token_record in tokens:
                token_id = int(token_record["id"])
                token = str(token_record["token"])
                token_type, is_valid, error_msg = (
                    await ZAITokenValidator.validate_token(token)
                )
                await self.update_token_type(token_id, token_type)

                if token_type == "user" and is_valid:
                    stats["valid"] += 1
                elif token_type == "guest":
                    stats["guest"] += 1
                    stats["invalid_token_ids"].append(token_id)
                else:
                    stats["invalid"] += 1
                    stats["invalid_token_ids"].append(token_id)
                    if error_msg:
                        logger.warning(
                            "⚠️ Token 验证失败: id={}, type={}, error={}",
                            token_id,
                            token_type,
                            error_msg,
                        )

            logger.info(
                "✅ 批量验证完成: 有效 {}, 匿名 {}, 无效 {}",
                stats["valid"],
                stats["guest"],
                stats["invalid"],
            )
            return stats
        except Exception as exc:
            logger.error(f"❌ 批量验证失败: {exc}")
            return {
                "checked": 0,
                "valid": 0,
                "guest": 0,
                "invalid": 0,
                "invalid_token_ids": [],
            }

    async def validate_all_tokens(self, provider: str = "zai") -> Dict[str, int]:
        stats = await self.validate_tokens_detailed(provider)
        return {
            "valid": int(stats.get("valid", 0) or 0),
            "guest": int(stats.get("guest", 0) or 0),
            "invalid": int(stats.get("invalid", 0) or 0),
        }
