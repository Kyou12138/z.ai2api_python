"""Token 相关表结构定义。"""

from app.services.database import normalize_db_type


def get_token_schema_statements(db_type: str) -> list[str]:
    """根据数据库类型返回建表语句。"""
    if normalize_db_type(db_type) == "postgresql":
        return [
            """
            CREATE TABLE IF NOT EXISTS tokens (
                id BIGSERIAL PRIMARY KEY,
                provider TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                token_type TEXT DEFAULT 'user',
                is_enabled BOOLEAN DEFAULT TRUE,
                priority INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, token)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS token_stats (
                id BIGSERIAL PRIMARY KEY,
                token_id BIGINT NOT NULL,
                total_requests INTEGER DEFAULT 0,
                successful_requests INTEGER DEFAULT 0,
                failed_requests INTEGER DEFAULT 0,
                last_success_time TIMESTAMP,
                last_failure_time TIMESTAMP,
                FOREIGN KEY (token_id) REFERENCES tokens(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tokens_provider ON tokens(provider)",
            "CREATE INDEX IF NOT EXISTS idx_tokens_enabled ON tokens(is_enabled)",
            "CREATE INDEX IF NOT EXISTS idx_token_stats_token_id ON token_stats(token_id)",
        ]

    return [
        """
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            token_type TEXT DEFAULT 'user',
            is_enabled BOOLEAN DEFAULT 1,
            priority INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider, token)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS token_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_id INTEGER NOT NULL,
            total_requests INTEGER DEFAULT 0,
            successful_requests INTEGER DEFAULT 0,
            failed_requests INTEGER DEFAULT 0,
            last_success_time DATETIME,
            last_failure_time DATETIME,
            FOREIGN KEY (token_id) REFERENCES tokens(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tokens_provider ON tokens(provider)",
        "CREATE INDEX IF NOT EXISTS idx_tokens_enabled ON tokens(is_enabled)",
        "CREATE INDEX IF NOT EXISTS idx_token_stats_token_id ON token_stats(token_id)",
    ]
