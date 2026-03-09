"""
请求日志数据访问层 (DAO)
提供请求日志的 CRUD 操作和查询功能
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.models.request_log import get_request_log_schema_statements
from app.services.database import get_database_backend
from app.utils.logger import logger


class RequestLogDAO:
    """请求日志数据访问对象"""

    def __init__(self):
        """初始化 DAO"""
        self.db = get_database_backend()
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        try:
            self.db.execute_statements_sync(
                get_request_log_schema_statements(self.db.db_type)
            )
            self._ensure_columns()
            logger.debug("请求日志表初始化成功")
        except Exception as e:
            logger.error(f"初始化请求日志表失败: {e}")

    def _ensure_columns(self):
        """为旧数据库补齐新增列。"""
        required_columns = {
            "endpoint": "TEXT DEFAULT ''",
            "source": "TEXT DEFAULT 'unknown'",
            "protocol": "TEXT DEFAULT 'unknown'",
            "client_name": "TEXT DEFAULT 'Unknown'",
            "status_code": "INTEGER DEFAULT 200",
        }

        with self.db.sync_connection() as conn:
            if self.db.is_sqlite:
                cursor = conn.execute("PRAGMA table_info(request_logs)")
                existing_columns = {row[1] for row in cursor.fetchall()}
                for column, definition in required_columns.items():
                    if column in existing_columns:
                        continue
                    conn.execute(
                        f"ALTER TABLE request_logs ADD COLUMN {column} {definition}"
                    )
            else:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = %s
                        """,
                        ("request_logs",),
                    )
                    existing_columns = {row[0] for row in cursor.fetchall()}
                    for column, definition in required_columns.items():
                        if column in existing_columns:
                            continue
                        cursor.execute(
                            f"ALTER TABLE request_logs ADD COLUMN IF NOT EXISTS {column} {definition}"
                        )
            conn.commit()

    @asynccontextmanager
    async def get_connection(self):
        """获取异步数据库连接"""
        async with self.db.connection() as conn:
            yield conn

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
        error_message: str = None
    ) -> int:
        """
        添加请求日志

        Args:
            provider: 提供商名称
            endpoint: 请求端点
            source: 请求来源标识
            protocol: 协议类型
            client_name: 客户端名称
            model: 模型名称
            status_code: 请求状态码
            success: 是否成功
            duration: 总耗时（秒）
            first_token_time: 首字延迟（秒）
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            error_message: 错误信息

        Returns:
            日志 ID
        """
        total_tokens = input_tokens + output_tokens

        async with self.get_connection() as conn:
            if self.db.is_postgresql:
                cursor = await conn.execute(
                    """
                    INSERT INTO request_logs
                    (provider, endpoint, source, protocol, client_name, model,
                     status_code, success, duration, first_token_time,
                     input_tokens, output_tokens, total_tokens, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
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
                        total_tokens,
                        error_message,
                    ),
                )
                row = await cursor.fetchone()
                await conn.commit()
                return int(row["id"]) if row else 0

            cursor = await conn.execute(
                """
                INSERT INTO request_logs
                (provider, endpoint, source, protocol, client_name, model,
                 status_code, success, duration, first_token_time,
                 input_tokens, output_tokens, total_tokens, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                    total_tokens,
                    error_message,
                ),
            )
            await conn.commit()
            return cursor.lastrowid or 0

    async def get_recent_logs(
        self,
        limit: int = 100,
        provider: str = None,
        model: str = None,
        success: bool = None,
        source: str = None,
    ) -> List[Dict]:
        """
        获取最近的请求日志

        Args:
            limit: 返回数量限制
            provider: 过滤提供商
            model: 过滤模型
            success: 过滤成功/失败状态

        Returns:
            日志列表
        """
        query = "SELECT * FROM request_logs WHERE 1=1"
        params = []

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        if model:
            query += " AND model = ?"
            params.append(model)

        if success is not None:
            query += " AND success = ?"
            params.append(success)

        if source:
            query += " AND source = ?"
            params.append(source)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        async with self.get_connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_logs_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        provider: str = None,
        model: str = None
    ) -> List[Dict]:
        """
        按时间范围获取日志

        Args:
            start_time: 开始时间
            end_time: 结束时间
            provider: 过滤提供商
            model: 过滤模型

        Returns:
            日志列表
        """
        query = "SELECT * FROM request_logs WHERE timestamp BETWEEN ? AND ?"
        params = [start_time, end_time]

        if provider:
            query += " AND provider = ?"
            params.append(provider)

        if model:
            query += " AND model = ?"
            params.append(model)

        query += " ORDER BY timestamp DESC"

        async with self.get_connection() as conn:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_model_stats_from_db(self, hours: int = 24) -> Dict:
        """
        从数据库获取模型统计（最近N小时）

        Args:
            hours: 小时数

        Returns:
            模型统计数据
        """
        start_time = datetime.now() - timedelta(hours=hours)

        async with self.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT
                    model,
                    COUNT(*) as total,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(total_tokens) as total_tokens,
                    AVG(duration) as avg_duration,
                    AVG(first_token_time) as avg_first_token_time
                FROM request_logs
                WHERE timestamp >= ?
                GROUP BY model
                ORDER BY total DESC
                """,
                (start_time,),
            )
            rows = await cursor.fetchall()

            result = {}
            for row in rows:
                model = row["model"]
                result[model] = {
                    "total": row["total"],
                    "success": row["success"] or 0,
                    "failed": row["failed"] or 0,
                    "input_tokens": row["input_tokens"] or 0,
                    "output_tokens": row["output_tokens"] or 0,
                    "total_tokens": row["total_tokens"] or 0,
                    "avg_duration": round(row["avg_duration"] or 0, 2),
                    "avg_first_token_time": round(row["avg_first_token_time"] or 0, 2),
                    "success_rate": round(
                        (((row["success"] or 0) / row["total"]) * 100)
                        if row["total"] > 0 else 0,
                        1,
                    ),
                }

            return result

    async def delete_old_logs(self, days: int = 30) -> int:
        """
        删除旧日志

        Args:
            days: 保留天数

        Returns:
            删除的记录数
        """
        cutoff_time = datetime.now() - timedelta(days=days)

        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM request_logs WHERE timestamp < ?",
                (cutoff_time,),
            )
            await conn.commit()
            return cursor.rowcount


_request_log_dao: Optional[RequestLogDAO] = None


def get_request_log_dao() -> RequestLogDAO:
    """
    获取请求日志 DAO 单例

    Returns:
        RequestLogDAO 实例
    """
    global _request_log_dao
    if _request_log_dao is None:
        _request_log_dao = RequestLogDAO()
    return _request_log_dao


def reset_request_log_dao() -> None:
    """重置请求日志 DAO 单例。"""
    global _request_log_dao
    _request_log_dao = None


def init_request_log_dao():
    """初始化请求日志 DAO"""
    global _request_log_dao
    _request_log_dao = RequestLogDAO()
    return _request_log_dao
