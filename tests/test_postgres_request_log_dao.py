from app.services.postgres_request_log_dao import _get_missing_required_columns


def test_get_missing_required_columns_only_returns_absent_columns():
    missing = _get_missing_required_columns(
        {
            "endpoint",
            "source",
            "protocol",
            "client_name",
            "status_code",
            "duration",
            "first_token_time",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "error_message",
            "created_at",
        }
    )

    assert missing == {
        "cache_creation_tokens": "INTEGER DEFAULT 0",
        "cache_read_tokens": "INTEGER DEFAULT 0",
    }
