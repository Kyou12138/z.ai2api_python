"""PostgreSQL 版请求日志 DAO。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.services.postgres_backend import get_postgres_pool
from app.utils.logger import logger

POSTGRES_REQUEST_LOG_SQL = """
CREATE TABLE IF NOT EXISTS request_logs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    provider TEXT NOT NULL,
    endpoint TEXT DEFAULT '',
    source TEXT DEFAULT 'unknown',
    protocol TEXT DEFAULT 'unknown',
    client_name TEXT DEFAULT 'Unknown',
    model TEXT NOT NULL,
    status_code INTEGER DEFAULT 200,
    success BOOLEAN NOT NULL,
    duration DOUBLE PRECISION,
    first_token_time DOUBLE PRECISION,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_request_logs_timestamp ON request_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_request_logs_model ON request_logs(model);
CREATE INDEX IF NOT EXISTS idx_request_logs_provider ON request_logs(provider);
CREATE INDEX IF NOT EXISTS idx_request_logs_source ON request_logs(source);
"""

POSTGRES_REQUEST_LOG_REQUIRED_COLUMNS = {
    "endpoint": "TEXT DEFAULT ''",
    "source": "TEXT DEFAULT 'unknown'",
    "protocol": "TEXT DEFAULT 'unknown'",
    "client_name": "TEXT DEFAULT 'Unknown'",
    "status_code": "INTEGER DEFAULT 200",
    "duration": "DOUBLE PRECISION",
    "first_token_time": "DOUBLE PRECISION",
    "input_tokens": "INTEGER DEFAULT 0",
    "output_tokens": "INTEGER DEFAULT 0",
    "cache_creation_tokens": "INTEGER DEFAULT 0",
    "cache_read_tokens": "INTEGER DEFAULT 0",
    "total_tokens": "INTEGER DEFAULT 0",
    "error_message": "TEXT",
    "created_at": "TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
}


def _get_missing_required_columns(
    existing_columns: set[str],
) -> dict[str, str]:
    return {
        column: definition
        for column, definition in POSTGRES_REQUEST_LOG_REQUIRED_COLUMNS.items()
        if column not in existing_columns
    }


def _normalize_trend_window(window: Optional[str], days: Optional[int]) -> str:
    if window:
        normalized = str(window).strip().lower()
    elif days == 30:
        normalized = "30d"
    elif days == 1:
        normalized = "24h"
    else:
        normalized = "7d"

    if normalized in {"24h", "7d", "30d"}:
        return normalized
    if normalized == "1d":
        return "24h"
    return "7d"


class PostgresRequestLogDAO:
    """PostgreSQL 请求日志 DAO。"""

    async def init_database(self):
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            await conn.execute(POSTGRES_REQUEST_LOG_SQL)
            await self._ensure_columns(conn)

    async def _ensure_columns(self, conn) -> None:
        """为旧 PostgreSQL 表结构补齐新增列。"""
        existing_rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'request_logs'
            """
        )
        existing_columns = {
            str(row["column_name"])
            for row in existing_rows
        }

        missing_columns = _get_missing_required_columns(existing_columns)
        for column, definition in missing_columns.items():
            await conn.execute(
                f"ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS "
                f"{column} {definition}"
            )
            logger.info("🩹 已为 request_logs 补齐列: {}", column)

    async def add_log(
        self,
        provider: str,
        endpoint: str,
        source: str,
        protocol: str,
        client_name: str,
        model: str,
        status_code: int,
        success: bool,
        duration: float = 0.0,
        first_token_time: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        total_tokens: Optional[int] = None,
        error_message: str = None,
    ) -> int:
        if total_tokens is None:
            total_tokens = input_tokens + output_tokens

        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO request_logs
                (provider, endpoint, source, protocol, client_name, model,
                 status_code, success, duration, first_token_time,
                 input_tokens, output_tokens, cache_creation_tokens,
                 cache_read_tokens, total_tokens, error_message)
                VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                 $11, $12, $13, $14, $15, $16)
                RETURNING id
                """,
                provider,
                endpoint,
                source,
                protocol,
                client_name,
                model,
                status_code,
                success,
                duration,
                first_token_time,
                input_tokens,
                output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
                total_tokens,
                error_message,
            )
        return int(row["id"])

    async def get_recent_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        provider: str = None,
        model: str = None,
        success: bool = None,
        source: str = None,
    ) -> List[Dict]:
        query = "SELECT * FROM request_logs WHERE 1=1"
        params: list[object] = []
        index = 1

        if provider:
            query += f" AND provider = ${index}"
            params.append(provider)
            index += 1
        if model:
            query += f" AND model = ${index}"
            params.append(model)
            index += 1
        if success is not None:
            query += f" AND success = ${index}"
            params.append(success)
            index += 1
        if source:
            query += f" AND source = ${index}"
            params.append(source)
            index += 1

        query += f" ORDER BY timestamp DESC, id DESC LIMIT ${index} OFFSET ${index + 1}"
        params.extend([limit, max(0, offset)])

        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def count_logs(
        self,
        provider: str = None,
        model: str = None,
        success: bool = None,
        source: str = None,
    ) -> int:
        query = "SELECT COUNT(*) AS total_count FROM request_logs WHERE 1=1"
        params: list[object] = []
        index = 1

        if provider:
            query += f" AND provider = ${index}"
            params.append(provider)
            index += 1
        if model:
            query += f" AND model = ${index}"
            params.append(model)
            index += 1
        if success is not None:
            query += f" AND success = ${index}"
            params.append(success)
            index += 1
        if source:
            query += f" AND source = ${index}"
            params.append(source)

        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)
        return int(row["total_count"] or 0) if row else 0

    async def get_logs_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        provider: str = None,
        model: str = None,
    ) -> List[Dict]:
        query = "SELECT * FROM request_logs WHERE timestamp BETWEEN $1 AND $2"
        params: list[object] = [start_time, end_time]
        index = 3

        if provider:
            query += f" AND provider = ${index}"
            params.append(provider)
            index += 1
        if model:
            query += f" AND model = ${index}"
            params.append(model)

        query += " ORDER BY timestamp DESC, id DESC"
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def get_provider_request_stats(self, provider: Optional[str] = None) -> Dict:
        query = """
            SELECT
                COUNT(*) AS total_requests,
                SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) AS successful_requests,
                SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) AS failed_requests,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(
                    SUM(
                        CASE WHEN cache_creation_tokens > 0 THEN 1 ELSE 0 END
                    ),
                    0
                ) AS cache_creation_requests,
                COALESCE(
                    SUM(CASE WHEN cache_read_tokens > 0 THEN 1 ELSE 0 END),
                    0
                ) AS cache_hit_requests,
                COALESCE(AVG(duration), 0) AS avg_duration,
                COALESCE(
                    AVG(
                        CASE
                            WHEN first_token_time > 0 THEN first_token_time
                        END
                    ),
                    0
                ) AS avg_first_token_time
            FROM request_logs
        """
        params: list[object] = []

        if provider:
            query += " WHERE provider = $1"
            params.append(provider)

        try:
            pool = await get_postgres_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(query, *params)
            if not row:
                return {
                    "total_requests": 0,
                    "successful_requests": 0,
                    "failed_requests": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_creation_requests": 0,
                    "cache_hit_requests": 0,
                    "avg_duration": 0.0,
                    "avg_first_token_time": 0.0,
                }

            return {
                "total_requests": int(row["total_requests"] or 0),
                "successful_requests": int(row["successful_requests"] or 0),
                "failed_requests": int(row["failed_requests"] or 0),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
                "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                "cache_creation_requests": int(row["cache_creation_requests"] or 0),
                "cache_hit_requests": int(row["cache_hit_requests"] or 0),
                "avg_duration": float(row["avg_duration"] or 0.0),
                "avg_first_token_time": float(row["avg_first_token_time"] or 0.0),
            }
        except Exception as exc:
            logger.error(f"❌ 获取请求统计失败: {exc}")
            return {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_requests": 0,
                "cache_hit_requests": 0,
                "avg_duration": 0.0,
                "avg_first_token_time": 0.0,
            }

    async def get_provider_usage_trend(
        self,
        provider: Optional[str] = None,
        days: Optional[int] = None,
        *,
        window: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> List[Dict]:
        trend_window = _normalize_trend_window(window, days)
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        if trend_window == "24h":
            bucket_count = 24
            current_hour = current_time.replace(
                minute=0,
                second=0,
                microsecond=0,
            )
            start_time = current_hour - timedelta(hours=bucket_count - 1)
            rows = await self._query_usage_trend_rows(
                provider,
                start_time,
                (
                    "to_char("
                    "date_trunc('hour', timestamp AT TIME ZONE 'UTC'), "
                    "'YYYY-MM-DD HH24:00:00'"
                    ")"
                ),
                "trend_bucket",
            )
            rows_by_bucket = {str(row["trend_bucket"]): dict(row) for row in rows}
            trend: List[Dict] = []
            for offset in range(bucket_count):
                bucket_time = start_time + timedelta(hours=offset)
                bucket_key = bucket_time.strftime("%Y-%m-%d %H:00:00")
                trend.append(
                    self._build_usage_trend_point(
                        row=rows_by_bucket.get(bucket_key, {}),
                        bucket=bucket_key,
                        label=bucket_time.strftime("%H:%M"),
                        tooltip_label=bucket_time.strftime("%Y-%m-%d %H:00"),
                    )
                )
            return trend

        bucket_count = 30 if trend_window == "30d" else 7
        current_date = current_time.date()
        start_date = current_date - timedelta(days=bucket_count - 1)
        start_time = datetime.combine(
            start_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        rows = await self._query_usage_trend_rows(
            provider,
            start_time,
            "to_char((timestamp AT TIME ZONE 'UTC')::date, 'YYYY-MM-DD')",
            "trend_bucket",
        )
        rows_by_bucket = {str(row["trend_bucket"]): dict(row) for row in rows}
        trend: List[Dict] = []

        for offset in range(bucket_count):
            bucket_date = start_date + timedelta(days=offset)
            bucket_key = bucket_date.isoformat()
            trend.append(
                self._build_usage_trend_point(
                    row=rows_by_bucket.get(bucket_key, {}),
                    bucket=bucket_key,
                    label=bucket_date.strftime("%m-%d"),
                    tooltip_label=bucket_date.strftime("%Y-%m-%d"),
                )
            )
        return trend

    async def _query_usage_trend_rows(
        self,
        provider: Optional[str],
        start_time: datetime,
        bucket_expression: str,
        bucket_alias: str,
    ):
        query = f"""
            SELECT
                {bucket_expression} AS {bucket_alias},
                COUNT(*) AS total_requests,
                SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) AS successful_requests,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens
            FROM request_logs
            WHERE timestamp >= $1
        """
        params: list[object] = [start_time]
        if provider:
            query += " AND provider = $2"
            params.append(provider)
        query += f" GROUP BY {bucket_expression} ORDER BY {bucket_alias} ASC"

        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *params)

    def _build_usage_trend_point(
        self,
        *,
        row: Dict,
        bucket: str,
        label: str,
        tooltip_label: str,
    ) -> Dict:
        total_requests = int(row.get("total_requests") or 0)
        successful_requests = int(row.get("successful_requests") or 0)
        cache_creation_tokens = int(row.get("cache_creation_tokens") or 0)
        cache_read_tokens = int(row.get("cache_read_tokens") or 0)
        return {
            "bucket": bucket,
            "label": label,
            "tooltip_label": tooltip_label,
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "failed_requests": max(0, total_requests - successful_requests),
            "input_tokens": int(row.get("input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "total_tokens": int(row.get("total_tokens") or 0),
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_total_tokens": cache_creation_tokens + cache_read_tokens,
            "success_rate": round(
                (successful_requests / total_requests * 100)
                if total_requests > 0
                else 0,
                1,
            ),
        }

    async def get_model_stats_from_db(self, hours: int = 24) -> Dict:
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    model,
                    COUNT(*) AS total,
                    SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) AS success,
                    SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) AS failed,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(AVG(duration), 0) AS avg_duration,
                    COALESCE(AVG(first_token_time), 0) AS avg_first_token_time
                FROM request_logs
                WHERE timestamp >= $1
                GROUP BY model
                ORDER BY total DESC
                """,
                start_time,
            )

        result = {}
        for row in rows:
            model = row["model"]
            result[model] = {
                "total": row["total"],
                "success": row["success"],
                "failed": row["failed"],
                "input_tokens": row["input_tokens"] or 0,
                "output_tokens": row["output_tokens"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "avg_duration": round(row["avg_duration"] or 0, 2),
                "avg_first_token_time": round(
                    row["avg_first_token_time"] or 0,
                    2,
                ),
                "success_rate": round(
                    (row["success"] / row["total"] * 100)
                    if row["total"] > 0
                    else 0,
                    1,
                ),
            }
        return result

    async def delete_old_logs(self, days: int = 30) -> int:
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        pool = await get_postgres_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                DELETE FROM request_logs
                WHERE timestamp < $1
                RETURNING id
                """,
                cutoff_time,
            )
        return len(rows)
