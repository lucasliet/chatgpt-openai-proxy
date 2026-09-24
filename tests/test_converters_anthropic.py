"""Testes dos conversores Anthropic ↔ Chat Completions."""

import json

from app.converters.anthropic import (
    anthropic_to_chat,
    chat_chunks_to_anthropic_events,
    chat_to_anthropic,
)


class TestAnthropicToChat:
    def test_system_string(self):
        chat = anthropic_to_chat(
            {
                "model": "claude-sonnet-4-5",
                "max_tokens": 1024,
                "system": "Você é útil.",
                "messages": [{"role": "user", "content": "oi"}],
            }
        )
        assert chat["messages"][0] == {"role": "system", "content": "Você é útil."}
        assert chat["max_completion_tokens"] == 1024

    def test_system_blocks(self):
        chat = anthropic_to_chat(
            {
                "model": "m",
                "max_tokens": 1,
                "system": [
                    {"type": "text", "text": "Parte 1. "},
                    {"type": "text", "text": "Parte 2."},
                ],
                "messages": [],
            }
        )
        assert chat["messages"][0]["content"] == "Parte 1. Parte 2."

    def test_conteudo_string_simples(self):
        chat = anthropic_to_chat(
            {"model": "m", "max_tokens": 1, "messages": [{"role": "user", "content": "oi"}]}
        )
        assert chat["messages"] == [{"role": "user", "content": "oi"}]

    def test_blocos_texto_e_imagem(self):
        chat = anthropic_to_chat(
            {
                "model": "m",
                "max_tokens": 1,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "veja:"},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": "QUJD",
                                },
                            },
                        ],
                    }
                ],
            }
        )
        assert chat["messages"][0]["content"] == [
            {"type": "text", "text": "veja:"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        ]

    def test_assistant_com_tool_use(self):
        chat = anthropic_to_chat(
            {
                "model": "m",
                "max_tokens": 1,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Deixa comigo."},
                            {
                                "type": "tool_use",
                                "id": "toolu_1",
                                "name": "buscar",
                                "input": {"q": "x"},
                            },
                        ],
                    }
                ],
            }
        )
        message = chat["messages"][0]
        assert message["role"] == "assistant"
        assert message["content"] == [{"type": "text", "text": "Deixa comigo."}]
        assert message["tool_calls"][0]["id"] == "toolu_1"
        assert message["tool_calls"][0]["function"]["name"] == "buscar"
        assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"q": "x"}

    def test_tool_result_vira_mensagem_tool(self):
        chat = anthropic_to_chat(
            {
                "model": "m",
                "max_tokens": 1,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "resultado"}
                        ],
                    }
                ],
            }
        )
        assert chat["messages"] == [
            {"role": "tool", "tool_call_id": "toolu_1", "content": "resultado"}
        ]

    def test_tools_e_tool_choice(self):
        chat = anthropic_to_chat(
            {
                "model": "m",
                "max_tokens": 1,
                "messages": [],
                "tools": [
                    {
                        "name": "buscar",
                        "description": "Busca",
                        "input_schema": {"type": "object", "properties": {}},
                    }
                ],
                "tool_choice": {"type": "tool", "name": "buscar"},
            }
        )
        assert chat["tools"][0]["function"]["name"] == "buscar"
        assert chat["tools"][0]["function"]["parameters"] == {
            "type": "object",
            "properties": {},
        }
        assert chat["tool_choice"] == {"type": "function", "function": {"name": "buscar"}}


class TestChatToAnthropic:
    def _chat_response(self, message, finish_reason="stop", usage=None):
        return {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": "gpt-5.1-codex",
            "choices": [
                {"index": 0, "message": message, "finish_reason": finish_reason}
            ],
            "usage": usage or {"prompt_tokens": 5, "completion_tokens": 6},
        }

    def test_texto(self):
        response = chat_to_anthropic(
            self._chat_response({"role": "assistant", "content": "Olá!"}), "claude-sonnet-4-5"
        )
        assert response["type"] == "message"
        assert response["role"] == "assistant"
        assert response["model"] == "claude-sonnet-4-5"
        assert response["content"] == [{"type": "text", "text": "Olá!"}]
        assert response["stop_reason"] == "end_turn"
        assert response["usage"] == {"input_tokens": 5, "output_tokens": 6}

    def test_tool_use(self):
        response = chat_to_anthropic(
            self._chat_response(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "buscar", "arguments": '{"q": 1}'},
                        }
                    ],
                },
                finish_reason="tool_calls",
            )
        )
        block = response["content"][0]
        assert block["type"] == "tool_use"
        assert block["input"] == {"q": 1}
        assert response["stop_reason"] == "tool_use"

    def test_stop_reason_length(self):
        response = chat_to_anthropic(
            self._chat_response({"role": "assistant", "content": "x"}, finish_reason="length")
        )
        assert response["stop_reason"] == "max_tokens"


class TestAnthropicStreamEvents:
    async def _chunks(self):
        yield {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "claude-sonnet-4-5",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
        yield {
            "choices": [
                {"index": 0, "delta": {"content": "Olá"}, "finish_reason": None}
            ]
        }
        yield {
            "choices": [
                {"index": 0, "delta": {"content": " mundo"}, "finish_reason": None}
            ]
        }
        yield {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }

    async def test_eventos_streaming_texto(self):
        events = [
            (event_type, data)
            async for event_type, data in chat_chunks_to_anthropic_events(
                self._chunks(), "claude-sonnet-4-5"
            )
        ]
        types = [t for t, _ in events]
        assert types == [
            "message_start",
            "content_block_start",
            "content_block_delta",
            "content_block_delta",
            "content_block_stop",
            "message_delta",
            "message_stop",
        ]

        start = events[0][1]["message"]
        assert start["model"] == "claude-sonnet-4-5"
        assert start["stop_reason"] is None

        deltas = [d for t, d in events if t == "content_block_delta"]
        assert deltas[0]["delta"] == {"type": "text_delta", "text": "Olá"}
        assert deltas[1]["delta"] == {"type": "text_delta", "text": " mundo"}

        message_delta = events[-2][1]
        assert message_delta["delta"]["stop_reason"] == "end_turn"
        assert message_delta["usage"] == {"input_tokens": 5, "output_tokens": 2}

    async def test_eventos_streaming_tool_use(self):
        async def chunks():
            yield {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "buscar", "arguments": ""},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
            yield {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '{"q"'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
            yield {
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": ': 1}'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
            yield {
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            }

        events = [
            (t, d)
            async for t, d in chat_chunks_to_anthropic_events(chunks(), "m")
        ]
        block_start = next(d for t, d in events if t == "content_block_start")
        assert block_start["content_block"]["type"] == "tool_use"
        assert block_start["content_block"]["name"] == "buscar"

        json_deltas = [
            d["delta"]["partial_json"]
            for t, d in events
            if t == "content_block_delta"
        ]
        assert "".join(json_deltas) == '{"q": 1}'

        message_delta = [d for t, d in events if t == "message_delta"][0]
        assert message_delta["delta"]["stop_reason"] == "tool_use"
