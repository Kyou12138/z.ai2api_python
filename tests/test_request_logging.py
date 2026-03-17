import json

import pytest

from app.utils.request_logging import (
    extract_claude_usage,
    extract_openai_usage,
    wrap_openai_stream_with_logging,
)
from app.utils.request_source import RequestSourceInfo


def test_extract_openai_usage_supports_cached_prompt_details():
    usage = extract_openai_usage(
        {
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
                "prompt_tokens_details": {
                    "cached_tokens": 32,
                },
            }
        }
    )

    assert usage == {
        "input_tokens": 120,
        "output_tokens": 45,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 32,
        "total_tokens": 165,
    }


def test_extract_claude_usage_supports_cache_token_fields():
    usage = extract_claude_usage(
        {
            "usage": {
                "input_tokens": 200,
                "output_tokens": 80,
                "cache_creation_input_tokens": 64,
                "cache_read_input_tokens": 48,
            }
        }
    )

    assert usage == {
        "input_tokens": 200,
        "output_tokens": 80,
        "cache_creation_tokens": 64,
        "cache_read_tokens": 48,
        "total_tokens": 392,
    }


@pytest.mark.asyncio
async def test_wrap_openai_stream_with_logging_handles_string_error_code(monkeypatch):
    captured = {}

    async def fake_write_request_log(**kwargs):
        captured.update(kwargs)

    async def fake_stream():
        yield (
            "data: "
            + json.dumps(
                {
                    "error": {
                        "message": "Oops, something went wrong.",
                        "code": "INTERNAL_ERROR",
                    }
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(
        "app.utils.request_logging.write_request_log",
        fake_write_request_log,
    )

    source_info = RequestSourceInfo(
        source="browser",
        protocol="openai",
        client_name="Browser",
        endpoint="/v1/chat/completions",
        user_agent="pytest",
    )

    chunks = []
    async for chunk in wrap_openai_stream_with_logging(
        fake_stream(),
        provider="zai",
        model="GLM-5",
        source_info=source_info,
        started_at=0.0,
    ):
        chunks.append(chunk)

    assert chunks == [
        'data: {"error": {"message": "Oops, something went wrong.", "code": "INTERNAL_ERROR"}}\n\n',
        "data: [DONE]\n\n",
    ]
    assert captured["success"] is False
    assert captured["status_code"] == 500
    assert captured["error_message"] == "Oops, something went wrong."
