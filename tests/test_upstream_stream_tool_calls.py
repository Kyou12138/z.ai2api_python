import json

import pytest

from app.core import upstream as upstream_module
from app.core.upstream import UpstreamClient
from app.models.schemas import Message, OpenAIRequest


class _FakeResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _build_request() -> OpenAIRequest:
    return OpenAIRequest(
        model="GLM-5",
        messages=[Message(role="user", content="hi")],
        stream=True,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "搜索网页",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )


@pytest.mark.asyncio
async def test_stream_tool_calls_stringifies_arguments(monkeypatch):
    monkeypatch.setattr(upstream_module.settings, "TOOL_SUPPORT", True)

    response = _FakeResponse(
        [
            "data: "
            + json.dumps(
                {
                    "type": "chat:completion",
                    "data": {
                        "phase": "answer",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "search_web",
                                    "arguments": {"q": "hello"},
                                },
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
            "data: "
            + json.dumps(
                {
                    "type": "chat:completion",
                    "data": {
                        "done": True,
                        "usage": {
                            "prompt_tokens": 1,
                            "completion_tokens": 2,
                            "total_tokens": 3,
                        },
                    },
                },
                ensure_ascii=False,
            ),
        ]
    )

    client = UpstreamClient()
    chunks = []
    async for chunk in client._handle_stream_response(
        response,
        "chatcmpl-test",
        "GLM-5",
        _build_request(),
        {"auth_mode": "authenticated"},
    ):
        chunks.append(chunk)

    assert len(chunks) == 4

    role_payload = json.loads(chunks[0][6:].strip())
    assert role_payload["choices"][0]["delta"] == {"role": "assistant"}

    tool_payload = json.loads(chunks[1][6:].strip())
    tool_call = tool_payload["choices"][0]["delta"]["tool_calls"][0]
    assert isinstance(tool_call["function"]["arguments"], str)
    assert json.loads(tool_call["function"]["arguments"]) == {"q": "hello"}

    finish_payload = json.loads(chunks[2][6:].strip())
    assert finish_payload["choices"][0]["finish_reason"] == "tool_calls"
    assert finish_payload["usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }

    assert chunks[3] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_stream_supports_event_and_multiline_data(monkeypatch):
    monkeypatch.setattr(upstream_module.settings, "TOOL_SUPPORT", True)

    response = _FakeResponse(
        [
            "event: chat:completion",
            'data: {"data": {',
            'data: "phase": "answer",',
            'data: "delta_content": "你好"',
            "data: }}",
            "",
            "event: chat:completion",
            'data: {"data": {"done": true}}',
            "",
        ]
    )

    client = UpstreamClient()
    chunks = []
    async for chunk in client._handle_stream_response(
        response,
        "chatcmpl-test",
        "GLM-5",
        _build_request(),
        {"auth_mode": "authenticated"},
    ):
        chunks.append(chunk)

    assert len(chunks) == 4

    role_payload = json.loads(chunks[0][6:].strip())
    assert role_payload["choices"][0]["delta"] == {"role": "assistant"}

    content_payload = json.loads(chunks[1][6:].strip())
    assert content_payload["choices"][0]["delta"] == {"content": "你好"}

    finish_payload = json.loads(chunks[2][6:].strip())
    assert finish_payload["choices"][0]["finish_reason"] == "stop"
    assert chunks[3] == "data: [DONE]\n\n"
