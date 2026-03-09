"""请求日志表结构定义。"""

from app.services.database import normalize_db_type


def get_request_log_schema_statements(db_type: str) -> list[str]:
    """根据数据库类型返回请求日志建表语句。"""
    if normalize_db_type(db_type) == "postgresql":
        return [
            """
            CREATE TABLE IF NOT EXISTS request_logs (
                id BIGSERIAL PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                total_tokens INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_request_logs_timestamp ON request_logs(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_request_logs_model ON request_logs(model)",
            "CREATE INDEX IF NOT EXISTS idx_request_logs_provider ON request_logs(provider)",
            "CREATE INDEX IF NOT EXISTS idx_request_logs_source ON request_logs(source)",
        ]

    return [
        """
        CREATE TABLE IF NOT EXISTS request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            provider TEXT NOT NULL,
            endpoint TEXT DEFAULT '',
            source TEXT DEFAULT 'unknown',
            protocol TEXT DEFAULT 'unknown',
            client_name TEXT DEFAULT 'Unknown',
            model TEXT NOT NULL,
            status_code INTEGER DEFAULT 200,
            success BOOLEAN NOT NULL,
            duration REAL,
            first_token_time REAL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_request_logs_timestamp ON request_logs(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_request_logs_model ON request_logs(model)",
        "CREATE INDEX IF NOT EXISTS idx_request_logs_provider ON request_logs(provider)",
        "CREATE INDEX IF NOT EXISTS idx_request_logs_source ON request_logs(source)",
    ]
