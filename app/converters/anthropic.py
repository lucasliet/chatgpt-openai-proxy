"""Conversão entre Anthropic Messages API e OpenAI Chat Completions.

O endpoint ``POST /v1/messages`` aceita o formato da Anthropic, converte para
o pipeline interno (chat completions → responses do Codex) e devolve a
resposta de volta no formato Anthropic, incluindo streaming SSE com os
eventos ``message_start`` / ``content_block_*`` / ``message_delta`` /
``message_stop``.
"""

import json
import time
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

FINISH_REASON_TO_STOP_REASON = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


def anthropic_to_chat(request: dict[str, Any]) -> dict[str, Any]:
    """Converte um Anthropic Messages request em ChatCompletionRequest."""
    chat_messages: list[dict[str, Any]] = []

    system = request.get("system")
    if system:
        system_text = _anthropic_text(system)
        if system_text:
            chat_messages.append({"role": "system", "content": system_text})

    for message in request.get("messages", []):
        role = message.get("role")
        content = message.get("content")

        if isinstance(content, str):
            chat_messages.append({"role": role, "content": content})
            continue

        text_parts: list[dict[str, Any]] = []
        image_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []

        for block in content or []:
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append({"type": "text", "text": block.get("text", "")})
            elif block_type == "image":
                source = block.get("source", {})
                if source.get("type") == "base64":
                    url = f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"
                    image_parts.append({"type": "image_url", "image_url": {"url": url}})
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input") or {}),
                        },
                    }
                )
            elif block_type == "tool_result":
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _tool_result_content(block.get("content")),
                    }
                )

        if role == "assistant":
            assistant_message: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                assistant_message["content"] = text_parts
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            chat_messages.append(assistant_message)
        else:
            user_content: list[dict[str, Any]] = [*text_parts, *image_parts]
            if user_content:
                chat_messages.append({"role": "user", "content": user_content})
            chat_messages.extend(tool_results)

    chat: dict[str, Any] = {
        "model": request.get("model", ""),
        "messages": chat_messages,
    }
    if request.get("max_tokens") is not None:
        chat["max_completion_tokens"] = request["max_tokens"]
    if request.get("temperature") is not None:
        chat["temperature"] = request["temperature"]
    if request.get("top_p") is not None:
        chat["top_p"] = request["top_p"]
    if request.get("stream"):
        chat["stream"] = True

    tools = request.get("tools")
    if tools:
        chat["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for tool in tools
        ]

    tool_choice = request.get("tool_choice")
    if tool_choice is not None:
        chat["tool_choice"] = _anthropic_tool_choice_to_chat(tool_choice)

    return chat


def chat_to_anthropic(
    chat_response: dict[str, Any], model: str | None = None
) -> dict[str, Any]:
    """Converte um ChatCompletionResponse em Anthropic Messages response."""
    choice = chat_response.get("choices", [{}])[0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")
    usage = chat_response.get("usage", {})

    content: list[dict[str, Any]] = []
    if message.get("content"):
        content.append({"type": "text", "text": message["content"]})
    for tool_call in message.get("tool_calls", []):
        function = tool_call.get("function", {})
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        content.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id", ""),
                "name": function.get("name", ""),
                "input": arguments,
            }
        )

    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model or chat_response.get("model", ""),
        "content": content,
        "stop_reason": FINISH_REASON_TO_STOP_REASON.get(finish_reason, "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


async def chat_chunks_to_anthropic_events(
    chunks: AsyncIterable[dict[str, Any]], model: str
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Transforma chunks de Chat Completions em eventos SSE da Anthropic.

    Yields tuplas ``(event_type, data)``; quem formata o frame SSE é a rota.
    """
    message_id = f"msg_{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    yield (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    open_block: dict[str, Any] | None = None  # {"kind": "text"|"tool_use", ...}
    block_index = -1
    tool_block_ids: dict[int, dict[str, str]] = {}
    output_tokens = 0
    input_tokens = 0

    async for chunk in chunks:
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})

            if delta.get("content"):
                if open_block is None:
                    block_index += 1
                    open_block = {"kind": "text"}
                    yield (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": block_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                yield (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {"type": "text_delta", "text": delta["content"]},
                    },
                )

            for tool_delta in delta.get("tool_calls", []):
                index = tool_delta.get("index", 0)
                known = tool_block_ids.setdefault(index, {"id": "", "name": ""})
                known["id"] = tool_delta.get("id") or known["id"]
                known["name"] = (
                    tool_delta.get("function", {}).get("name") or known["name"]
                )
                partial_json = tool_delta.get("function", {}).get("arguments", "")

                is_new_block = (
                    open_block is None
                    or open_block.get("kind") != "tool_use"
                    or open_block.get("index") != index
                )
                if is_new_block:
                    if open_block is not None:
                        yield (
                            "content_block_stop",
                            {"type": "content_block_stop", "index": block_index},
                        )
                    block_index += 1
                    open_block = {"kind": "tool_use", "index": index}
                    yield (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": block_index,
                            "content_block": {
                                "type": "tool_use",
                                "id": known["id"],
                                "name": known["name"],
                                "input": {},
                            },
                        },
                    )
                if partial_json:
                    yield (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": block_index,
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": partial_json,
                            },
                        },
                    )

            if choice.get("finish_reason") is not None:
                if open_block is not None:
                    yield (
                        "content_block_stop",
                        {"type": "content_block_stop", "index": block_index},
                    )
                    open_block = None

        usage = chunk.get("usage")
        if usage:
            output_tokens = usage.get("completion_tokens", output_tokens)
            input_tokens = usage.get("prompt_tokens", input_tokens)

        final_choice = chunk.get("choices", [{}])[0]
        if final_choice.get("finish_reason") is not None:
            stop_reason = FINISH_REASON_TO_STOP_REASON.get(
                final_choice["finish_reason"], "end_turn"
            )
            yield (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                },
            )
            yield ("message_stop", {"type": "message_stop"})
            return


def format_anthropic_sse(event_type: str, data: dict[str, Any]) -> bytes:
    """Serializa um evento Anthropic no formato SSE com linha ``event:``."""
    return (
        f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    ).encode("utf-8")


def _anthropic_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if block.get("type") == "text"
        )
    return ""


def _tool_result_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif block.get("type") == "image":
                parts.append("[image]")
        return "".join(parts)
    return json.dumps(content)


def _anthropic_tool_choice_to_chat(tool_choice: Any) -> Any:
    if isinstance(tool_choice, str):
        return tool_choice
    choice_type = tool_choice.get("type")
    if choice_type == "tool":
        return {"type": "function", "function": {"name": tool_choice.get("name", "")}}
    return choice_type  # "auto" | "none" | "any" → passa adiante quando possível
