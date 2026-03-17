from datetime import datetime, timezone

from app.services.postgres_request_log_dao import (
    _coerce_datetime_for_column,
    _get_legacy_time_columns,
    _get_missing_required_columns,
)


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


def test_get_legacy_time_columns_detects_naive_timestamp_columns():
    legacy_columns = _get_legacy_time_columns(
        {
            "timestamp": "timestamp without time zone",
            "created_at": "timestamp with time zone",
        }
    )

    assert legacy_columns == ["timestamp"]


def test_coerce_datetime_for_column_converts_aware_value_to_naive_utc():
    aware = datetime(2026, 3, 18, 8, 0, 0, tzinfo=timezone.utc)

    normalized = _coerce_datetime_for_column(aware, use_timezone=False)

    assert normalized.tzinfo is None
    assert normalized == datetime(2026, 3, 18, 8, 0, 0)
