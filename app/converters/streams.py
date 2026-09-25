"""Parsing de SSE e conversão de streams Responses → Chat Completions.

Port fiel do ``stream-converter.ts``: emite o chunk inicial de role, deltas de
texto, tool_calls progressivos e o chunk final com finish_reason e usage,
seguido de ``[DONE]``.
"""

import json
import time
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Any

DONE_FRAME = b"data: [DONE]\n\n"


def format_sse(data: Any) -> bytes:
    """Serializa um objeto como frame SSE ``data: {json}\\n\\n``."""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


async def iter_sse_events(chunks: AsyncIterable[bytes]) -> AsyncIterator[dict[str, Any]]:
    """Parseia bytes SSE em eventos JSON (um por frame, separados por linha em branco)."""
    buffer = b""
    async for chunk in chunks:
        buffer += chunk
        frames = buffer.split(b"\n\n")
        buffer = frames.pop()
        for frame in frames:
            event = _parse_frame(frame)
            if event is not None:
                yield event

    tail = buffer.strip()
    if tail:
        event = _parse_frame(tail)
        if event is not None:
            yield event


def _parse_frame(frame: bytes) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for line in frame.split(b"\n"):
        if line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip().decode("utf-8"))
    if not data_lines:
        return None
    raw = "\n".join(data_lines)
    if raw == "[DONE]":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@dataclass
class _ToolCallAccumulator:
    index: int
    id: str
    name: str
    arguments: str


async def aggregate_responses_events(
    events: AsyncIterable[dict[str, Any]],
) -> dict[str, Any] | None:
    """Agrega um stream de eventos Responses no objeto Response completo.

    Usa o objeto ``response`` do evento ``response.completed`` como base, mas
    não confia em ``output`` vir preenchido (a engine litellm o devolve vazio
    em alguns modelos): nesse caso reconstrói os itens de saída a partir dos
    deltas de texto e dos eventos de function call. Retorna ``None`` se o
    stream terminar sem ``response.completed``.
    """
    completed: dict[str, Any] | None = None
    text_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}

    async for event in events:
        event_type = event.get("type")
        if event_type == "response.output_text.delta":
            text_parts.append(event.get("delta", ""))
        elif event_type == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                index = event.get("output_index", 0)
                tool_calls[index] = {
                    "id": item.get("call_id"),
                    "name": item.get("name"),
                    "arguments": "",
                }
        elif event_type == "response.function_call_arguments.delta":
            index = event.get("output_index", 0)
            if index in tool_calls:
                tool_calls[index]["arguments"] += event.get("delta", "")
        elif event_type == "response.completed":
            response = event.get("response")
            if isinstance(response, dict):
                completed = response

    if completed is None:
        return None
    if not completed.get("output"):
        output: list[dict[str, Any]] = []
        if text_parts:
            output.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "".join(text_parts)}],
                }
            )
        for index in sorted(tool_calls):
            call = tool_calls[index]
            output.append(
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["name"],
                    "arguments": call["arguments"],
                }
            )
        completed["output"] = output
    return completed


async def responses_events_to_chat_chunks(
    events: AsyncIterable[dict[str, Any]], model: str
) -> AsyncIterator[dict[str, Any]]:
    """Transforma eventos Responses em chunks de Chat Completions."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    tool_calls: dict[int, _ToolCallAccumulator] = {}
    first_chunk_sent = False

    async def maybe_role_chunk() -> dict[str, Any] | None:
        nonlocal first_chunk_sent
        if first_chunk_sent:
            return None
        first_chunk_sent = True
        return _build_chunk(chat_id, model, created, {"role": "assistant"}, None)

    async for event in events:
        event_type = event.get("type")

        if event_type == "response.output_text.delta":
            role_chunk = await maybe_role_chunk()
            if role_chunk is not None:
                yield role_chunk
            yield _build_chunk(chat_id, model, created, {"content": event.get("delta", "")}, None)

        elif event_type == "response.function_call_arguments.delta":
            index = event.get("output_index", 0)
            if index not in tool_calls:
                tool_calls[index] = _ToolCallAccumulator(
                    index=index,
                    id=event.get("call_id", ""),
                    name=event.get("name", ""),
                    arguments="",
                )
            tool_calls[index].arguments += event.get("delta", "")
            role_chunk = await maybe_role_chunk()
            if role_chunk is not None:
                yield role_chunk
            yield _build_chunk(
                chat_id,
                model,
                created,
                {},
                None,
                [{"index": index, "function": {"arguments": event.get("delta", "")}}],
            )

        elif event_type == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") != "function_call":
                continue
            index = event.get("output_index", 0)
            tool_calls[index] = _ToolCallAccumulator(
                index=index,
                id=item.get("call_id", ""),
                name=item.get("name", ""),
                arguments="",
            )
            role_chunk = await maybe_role_chunk()
            if role_chunk is not None:
                yield role_chunk
            yield _build_chunk(
                chat_id,
                model,
                created,
                {},
                None,
                [
                    {
                        "index": index,
                        "id": item.get("call_id", ""),
                        "type": "function",
                        "function": {"name": item.get("name", ""), "arguments": ""},
                    }
                ],
            )

        elif event_type == "response.completed":
            yield _build_final_chunk(event, chat_id, model, created, tool_calls)
            return


def _build_chunk(
    chat_id: str,
    model: str,
    created: int,
    delta: dict[str, Any] | None,
    finish_reason: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if tool_calls is not None:
        delta_payload: dict[str, Any] = {"tool_calls": tool_calls}
    else:
        delta_payload = delta or {}
    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "delta": delta_payload, "finish_reason": finish_reason}
        ],
    }


def _build_final_chunk(
    event: dict[str, Any],
    chat_id: str,
    model: str,
    created: int,
    tool_calls: dict[int, _ToolCallAccumulator],
) -> dict[str, Any]:
    usage = event.get("response", {}).get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }
