import type {
  ChatCompletionRequest,
  ChatContentPart,
  ChatMessage,
  ChatTool,
} from "../types/chat-completions";
import type {
  ResponsesFunctionCallOutput,
  ResponsesInputMessage,
  ResponsesRequest,
  ResponsesTool,
} from "../types/responses";

const DEFAULT_INSTRUCTIONS = "You are a helpful assistant.";

/**
 * Converts an OpenAI Chat Completions request into the Responses API payload
 * expected by the Codex backend, including the mandatory `store: false` flag
 * and a fallback instruction string (the Codex endpoint rejects empty ones).
 */
export function convertChatToResponses(request: ChatCompletionRequest): ResponsesRequest {
  const { instructions, input } = convertMessages(request.messages);

  const payload: ResponsesRequest = {
    model: request.model,
    input,
    store: false,
  };

  const effectiveInstructions = instructions || DEFAULT_INSTRUCTIONS;
  payload.instructions = effectiveInstructions;

  if (request.tools?.length) {
    payload.tools = request.tools.map(convertTool);
  }
  if (request.tool_choice !== undefined) {
    payload.tool_choice = convertToolChoice(request.tool_choice);
  }
  if (request.temperature !== undefined) payload.temperature = request.temperature;
  if (request.top_p !== undefined) payload.top_p = request.top_p;
  if (request.max_tokens !== undefined) payload.max_output_tokens = request.max_tokens;
  if (request.max_completion_tokens !== undefined) {
    payload.max_output_tokens = request.max_completion_tokens;
  }
  if (request.stream) payload.stream = true;

  return payload;
}

function convertMessages(messages: ChatMessage[]): {
  instructions: string;
  input: ResponsesRequest["input"];
} {
  const instructions: string[] = [];
  const input: ResponsesRequest["input"] = [];

  for (const message of messages) {
    if (message.role === "system" || message.role === "developer") {
      const text = extractText(message.content);
      if (text) instructions.push(text);
      continue;
    }

    if (message.role === "tool") {
      input.push(convertToolResult(message));
      continue;
    }

    input.push(convertAssistantOrUser(message));
  }

  return { instructions: instructions.join("\n\n"), input };
}

function convertAssistantOrUser(message: ChatMessage): ResponsesInputMessage {
  const content = convertContent(message.content);
  return {
    type: "message",
    role: message.role,
    content,
  };
}

function convertToolResult(message: ChatMessage): ResponsesFunctionCallOutput {
  return {
    type: "function_call_output",
    call_id: message.tool_call_id ?? "",
    output: extractText(message.content) ?? "",
  };
}

function convertContent(content: ChatMessage["content"]): string | ChatContentPart[] {
  if (content === null || content === undefined) return "";
  if (typeof content === "string") return content;
  return content;
}

function extractText(content: ChatMessage["content"]): string | null {
  if (content === null || content === undefined) return null;
  if (typeof content === "string") return content;
  return content
    .filter((part): part is { type: "text"; text: string } => part.type === "text")
    .map((part) => part.text)
    .join("");
}

function convertTool(tool: ChatTool): ResponsesTool {
  return {
    type: "function",
    name: tool.function.name,
    description: tool.function.description,
    parameters: tool.function.parameters,
  };
}

function convertToolChoice(
  choice: NonNullable<ChatCompletionRequest["tool_choice"]>,
): ResponsesRequest["tool_choice"] {
  if (typeof choice === "string") return choice;
  return { type: "function", name: choice.function.name };
}
