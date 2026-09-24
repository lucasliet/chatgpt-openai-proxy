"""Conversão entre Chat Completions e Responses API — port fiel do proxy TS.

Regras preservadas do código original:

- ``store: false`` sempre presente (endpoint Codex exige).
- Fallback ``"You are a helpful assistant."`` quando não há system/developer
  (o backend Codex rejeita ``instructions`` vazio).
- system/developer viram ``instructions`` concatenadas com ``\\n\\n``.
- mensagens ``tool`` viram ``function_call_output``.
- ``tools[].function`` é achatado para ``tools[].{name, description, parameters}``.
- ``max_completion_tokens`` sobrescreve ``max_tokens`` (ambos viram
  ``max_output_tokens``).
"""

from typing import Any

DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


def chat_to_responses(request: dict[str, Any]) -> dict[str, Any]:
    """Converte um ChatCompletionRequest no payload Responses do Codex."""
    instructions, input_items = _convert_messages(request.get("messages", []))

    payload: dict[str, Any] = {
        "model": request["model"],
        "input": input_items,
        "store": False,
        "instructions": instructions or DEFAULT_INSTRUCTIONS,
    }

    tools = request.get("tools")
    if tools:
        payload["tools"] = [_convert_tool(tool) for tool in tools]
    if request.get("tool_choice") is not None:
        payload["tool_choice"] = _convert_tool_choice(request["tool_choice"])
    if request.get("temperature") is not None:
        payload["temperature"] = request["temperature"]
    if request.get("top_p") is not None:
        payload["top_p"] = request["top_p"]
    if request.get("max_tokens") is not None:
        payload["max_output_tokens"] = request["max_tokens"]
    if request.get("max_completion_tokens") is not None:
        payload["max_output_tokens"] = request["max_completion_tokens"]
    if request.get("stream"):
        payload["stream"] = True

    return payload


def responses_to_chat(response: dict[str, Any]) -> dict[str, Any]:
    """Converte uma Responses API response em ChatCompletionResponse."""
    import time

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for item in response.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text_parts.append(part.get("text", ""))
        else:
            tool_calls.append(
                {
                    "id": item.get("call_id"),
                    "type": "function",
                    "function": {
                        "name": item.get("name"),
                        "arguments": item.get("arguments"),
                    },
                }
            )

    has_tool_calls = len(tool_calls) > 0
    usage = response.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    return {
        "id": response.get("id"),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": response.get("model"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "".join(text_parts) if text_parts else None,
                    **({"tool_calls": tool_calls} if has_tool_calls else {}),
                },
                "finish_reason": "tool_calls" if has_tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        if role in ("system", "developer"):
            text = _extract_text(message.get("content"))
            if text:
                instructions.append(text)
        elif role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id", ""),
                    "output": _extract_text(message.get("content")) or "",
                }
            )
        else:
            input_items.append(
                {
                    "type": "message",
                    "role": role,
                    "content": message.get("content") or "",
                }
            )

    return "\n\n".join(instructions), input_items


def _extract_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if part.get("type") == "text"
        )
    return None


def _convert_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function", {})
    converted: dict[str, Any] = {"type": "function", "name": function.get("name")}
    if function.get("description") is not None:
        converted["description"] = function["description"]
    if function.get("parameters") is not None:
        converted["parameters"] = function["parameters"]
    return converted


def _convert_tool_choice(choice: Any) -> Any:
    if isinstance(choice, str):
        return choice
    function = choice.get("function", {})
    return {"type": "function", "name": function.get("name")}
