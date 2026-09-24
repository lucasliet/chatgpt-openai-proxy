"""Testes do parsing SSE e da conversão de stream Responses → Chat."""

import json

from app.converters.streams import (
    DONE_FRAME,
    format_sse,
    iter_sse_events,
    responses_events_to_chat_chunks,
)


async def _byte_source(*chunks: bytes):
    for chunk in chunks:
        yield chunk


class TestIterSseEvents:
    async def test_frames_multiplos_por_chunk(self):
        events = [
            {"type": "a", "n": 1},
            {"type": "b", "n": 2},
        ]
        payload = "".join(
            f"data: {json.dumps(e)}\n\n" for e in events
        ).encode()
        # Tudo em um único chunk.
        result = [e async for e in iter_sse_events(_byte_source(payload))]
        assert result == events

    async def test_frames_divididos_entre_chunks(self):
        frame = b'data: {"type": "x"}\n\n'
        result = [
            e
            async for e in iter_sse_events(
                _byte_source(frame[:7], frame[7:15], frame[15:])
            )
        ]
        assert result == [{"type": "x"}]

    async def test_done_e_frames_invalidos_sao_ignorados(self):
        payload = b'data: [DONE]\n\ndata: nao-json\n\n: comentario\n\n'
        result = [e async for e in iter_sse_events(_byte_source(payload))]
        assert result == []


class TestResponsesEventsToChatChunks:
    async def _events(self, events):
        for event in events:
            yield event

    async def test_stream_texto_completo(self):
        events = [
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "Olá"},
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "!"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "model": "gpt-5.1-codex",
                    "output": [],
                    "usage": {"input_tokens": 11, "output_tokens": 4},
                },
            },
        ]
        chunks = [
            c
            async for c in responses_events_to_chat_chunks(
                self._events(events), "gpt-5.1-codex"
            )
        ]

        assert chunks[0]["object"] == "chat.completion.chunk"
        assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}
        assert chunks[1]["choices"][0]["delta"] == {"content": "Olá"}
        assert chunks[2]["choices"][0]["delta"] == {"content": "!"}

        final = chunks[3]
        assert final["choices"][0]["finish_reason"] == "stop"
        assert final["usage"] == {
            "prompt_tokens": 11,
            "completion_tokens": 4,
            "total_tokens": 15,
        }

    async def test_stream_com_tool_calls(self):
        events = [
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "buscar",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "item_id": "fc_1",
                "call_id": "call_1",
                "name": "buscar",
                "delta": '{"q"',
            },
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "item_id": "fc_1",
                "call_id": "call_1",
                "name": "buscar",
                "delta": ': 1}',
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_2",
                    "model": "gpt-5.1-codex",
                    "output": [],
                    "usage": {"input_tokens": 20, "output_tokens": 8},
                },
            },
        ]
        chunks = [
            c
            async for c in responses_events_to_chat_chunks(
                self._events(events), "gpt-5.1-codex"
            )
        ]

        added = chunks[1]
        assert added["choices"][0]["delta"]["tool_calls"] == [
            {
                "index": 0,
                "id": "call_1",
                "type": "function",
                "function": {"name": "buscar", "arguments": ""},
            }
        ]

        deltas = [
            c["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
            for c in chunks[2:4]
        ]
        assert deltas == ['{"q"', ': 1}']

        final = chunks[4]
        assert final["choices"][0]["finish_reason"] == "tool_calls"

    async def test_para_no_response_completed(self):
        events = [
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "x"},
            {
                "type": "response.completed",
                "response": {"id": "r", "model": "m", "output": [], "usage": {"input_tokens": 1, "output_tokens": 1}},
            },
            # Evento extra após completed não deve ser processado.
            {"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "y"},
        ]
        chunks = [
            c
            async for c in responses_events_to_chat_chunks(self._events(events), "m")
        ]
        textos = [
            c["choices"][0]["delta"].get("content")
            for c in chunks
            if "content" in c["choices"][0]["delta"]
        ]
        assert textos == ["x"]


def test_format_sse_e_done():
    assert format_sse({"a": 1}) == b'data: {"a": 1}\n\n'
    assert DONE_FRAME == b"data: [DONE]\n\n"
