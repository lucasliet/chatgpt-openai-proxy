import type {
  ChatCompletionResponse,
  ChatFunctionCall,
} from "../types/chat-completions";
import type { ResponsesResponse, ResponsesOutputItem } from "../types/responses";

/**
 * Converts a non-streaming Responses API response into the OpenAI Chat
 * Completions response shape, mapping message outputs and function calls and
 * computing the finish reason and token usage.
 */
export function convertResponsesToChat(response: ResponsesResponse): ChatCompletionResponse {
  const textParts: string[] = [];
  const toolCalls: ChatFunctionCall[] = [];

  for (const item of response.output) {
    collectItem(item, textParts, toolCalls);
  }

  const hasToolCalls = toolCalls.length > 0;
  const content = textParts.length > 0 ? textParts.join("") : null;

  return {
    id: response.id,
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: response.model,
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content,
          ...(hasToolCalls ? { tool_calls: toolCalls } : {}),
        },
        finish_reason: hasToolCalls ? "tool_calls" : "stop",
      },
    ],
    usage: {
      prompt_tokens: response.usage.input_tokens,
      completion_tokens: response.usage.output_tokens,
      total_tokens: response.usage.input_tokens + response.usage.output_tokens,
    },
  };
}

function collectItem(
  item: ResponsesOutputItem,
  textParts: string[],
  toolCalls: ChatFunctionCall[],
): void {
  if (item.type === "message") {
    for (const part of item.content) {
      if (part.type === "output_text") textParts.push(part.text);
    }
    return;
  }

  toolCalls.push({
    id: item.call_id,
    type: "function",
    function: { name: item.name, arguments: item.arguments },
  });
}
