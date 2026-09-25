"""Testes dos conversores chat ↔ responses."""

from app.converters.chat_completions import (
    DEFAULT_INSTRUCTIONS,
    chat_to_responses,
    responses_to_chat,
)


class TestChatToResponses:
    def test_store_false_sempre_presente(self):
        payload = chat_to_responses({"model": "gpt-5.5", "messages": []})
        assert payload["store"] is False

    def test_instructions_fallback_quando_sem_system(self):
        payload = chat_to_responses({"model": "m", "messages": [{"role": "user", "content": "oi"}]})
        assert payload["instructions"] == DEFAULT_INSTRUCTIONS

    def test_system_e_developer_viram_instructions(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [
                    {"role": "system", "content": "Regra 1"},
                    {"role": "developer", "content": "Regra 2"},
                    {"role": "user", "content": "oi"},
                ],
            }
        )
        assert payload["instructions"] == "Regra 1\n\nRegra 2"
        assert payload["input"] == [{"type": "message", "role": "user", "content": "oi"}]

    def test_mensagem_tool_vira_function_call_output(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [
                    {"role": "tool", "tool_call_id": "call_1", "content": "resultado"},
                ],
            }
        )
        assert payload["input"] == [
            {"type": "function_call_output", "call_id": "call_1", "output": "resultado"}
        ]

    def test_tools_achatadas(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "buscar",
                            "description": "Busca",
                            "parameters": {"type": "object"},
                        },
                    }
                ],
            }
        )
        assert payload["tools"] == [
            {"type": "function", "name": "buscar", "description": "Busca", "parameters": {"type": "object"}}
        ]

    def test_tool_choice_function(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [],
                "tool_choice": {"type": "function", "function": {"name": "buscar"}},
            }
        )
        assert payload["tool_choice"] == {"type": "function", "name": "buscar"}

    def test_max_tokens_nao_e_repassado(self):
        # O backend do plano rejeita max_output_tokens ("Unsupported parameter").
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [],
                "max_tokens": 100,
                "max_completion_tokens": 200,
            }
        )
        assert "max_output_tokens" not in payload

    def test_parametros_opcionais(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "oi"}]}],
                "temperature": 0.5,
                "top_p": 0.9,
                "stream": True,
            }
        )
        assert payload["temperature"] == 0.5
        assert payload["top_p"] == 0.9
        assert payload["stream"] is True

    def test_vision_text_e_image_url_viram_input(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "veja:"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,QUJD",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
            }
        )
        assert payload["input"] == [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "veja:"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,QUJD",
                        "detail": "high",
                    },
                ],
            }
        ]

    def test_vision_image_url_string_e_detail_invalido(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": "https://ex.com/a.png",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://ex.com/b.png", "detail": "foo"},
                            },
                            {"type": "image_url", "image_url": {"url": ""}},
                        ],
                    }
                ],
            }
        )
        assert payload["input"][0]["content"] == [
            {"type": "input_image", "image_url": "https://ex.com/a.png"},
            {"type": "input_image", "image_url": "https://ex.com/b.png"},
        ]

    def test_vision_input_image_passthrough(self):
        payload = chat_to_responses(
            {
                "model": "m",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "oi"},
                            {"type": "input_image", "image_url": "https://ex.com/a.png"},
                        ],
                    }
                ],
            }
        )
        assert payload["input"][0]["content"] == [
            {"type": "input_text", "text": "oi"},
            {"type": "input_image", "image_url": "https://ex.com/a.png"},
        ]


class TestResponsesToChat:
    def _responses_response(self, output, usage=None):
        return {
            "id": "resp_1",
            "object": "response",
            "model": "gpt-5.5",
            "output": output,
            "usage": usage or {"input_tokens": 3, "output_tokens": 7},
        }

    def test_texto_simples(self):
        response = self._responses_response(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Olá!"}],
                }
            ]
        )
        chat = responses_to_chat(response)
        assert chat["object"] == "chat.completion"
        assert chat["choices"][0]["message"]["content"] == "Olá!"
        assert chat["choices"][0]["finish_reason"] == "stop"
        assert chat["usage"] == {"prompt_tokens": 3, "completion_tokens": 7, "total_tokens": 10}

    def test_function_call(self):
        response = self._responses_response(
            [
                {
                    "type": "function_call",
                    "call_id": "call_9",
                    "name": "buscar",
                    "arguments": '{"q": "x"}',
                }
            ]
        )
        chat = responses_to_chat(response)
        message = chat["choices"][0]["message"]
        assert message["content"] is None
        assert message["tool_calls"] == [
            {
                "id": "call_9",
                "type": "function",
                "function": {"name": "buscar", "arguments": '{"q": "x"}'},
            }
        ]
        assert chat["choices"][0]["finish_reason"] == "tool_calls"
