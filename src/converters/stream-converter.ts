import type { ChatCompletionChunk } from "../types/chat-completions";
import type {
  ResponseCompletedEvent,
  ResponseFunctionCallArgumentsDeltaEvent,
  ResponseOutputItemAddedEvent,
  ResponsesStreamEvent,
} from "../types/responses";

interface ToolCallAccumulator {
  index: number;
  id: string;
  name: string;
  arguments: string;
}

/**
 * Parses raw Server-Sent Events bytes into typed Responses API stream events.
 * Returns one event per SSE frame delimited by a blank line.
 */
export async function* parseSseEvents(
  stream: ReadableStream<Uint8Array>,
): AsyncIterable<ResponsesStreamEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const event = parseFrame(frame);
        if (event) yield event;
      }
    }

    if (buffer.trim()) {
      const event = parseFrame(buffer);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}

function parseFrame(frame: string): ResponsesStreamEvent | null {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) return null;

  const raw = dataLines.join("\n");
  if (raw === "[DONE]") return null;

  try {
    return JSON.parse(raw) as ResponsesStreamEvent;
  } catch {
    return null;
  }
}

/**
 * Transforms a Responses API SSE stream into the OpenAI Chat Completions chunk
 * stream, emitting the initial role chunk, text deltas, tool-call argument
 * deltas, and the final chunk with finish reason and usage followed by `[DONE]`.
 */
export function convertResponsesStreamToChat(
  stream: ReadableStream<Uint8Array>,
  model: string,
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const toolCallsByIndex = new Map<number, ToolCallAccumulator>();
  let id = `chatcmpl-${crypto.randomUUID()}`;
  let created = Math.floor(Date.now() / 1000);
  let firstChunkSent = false;

  return new ReadableStream({
    async start(controller) {
      try {
        for await (const event of parseSseEvents(stream)) {
          const chunks = toChunks(event, model, id, created, toolCallsByIndex, () => {
            if (!firstChunkSent) {
              firstChunkSent = true;
              return true;
            }
            return false;
          });
          if (!firstChunkSent && chunks.length > 0) firstChunkSent = true;

          for (const chunk of chunks) {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`));
          }

          if (event.type === "response.completed") break;
        }

        controller.enqueue(encoder.encode("data: [DONE]\n\n"));
        controller.close();
      } catch (error) {
        controller.error(error);
      }
    },
  });
}

function toChunks(
  event: ResponsesStreamEvent,
  model: string,
  id: string,
  created: number,
  toolCalls: Map<number, ToolCallAccumulator>,
  isFirstChunk: () => boolean,
): ChatCompletionChunk[] {
  switch (event.type) {
    case "response.output_text.delta": {
      const chunks: ChatCompletionChunk[] = [];
      if (isFirstChunk()) {
        chunks.push(buildChunk(id, model, created, { role: "assistant" }, null));
      }
      chunks.push(
        buildChunk(id, model, created, { content: event.delta }, null),
      );
      return chunks;
    }

    case "response.function_call_arguments.delta": {
      ensureToolCall(toolCalls, event);
      const existing = toolCalls.get(event.output_index);
      if (existing) existing.arguments += event.delta;

      const chunks: ChatCompletionChunk[] = [];
      if (isFirstChunk()) {
        chunks.push(buildChunk(id, model, created, { role: "assistant" }, null));
      }
      chunks.push(
        buildChunk(id, model, created, {}, null, [
          {
            index: event.output_index,
            function: { arguments: event.delta },
          },
        ]),
      );
      return chunks;
    }

    case "response.output_item.added": {
      return handleItemAdded(event, id, model, created, toolCalls, isFirstChunk);
    }

    case "response.completed": {
      return [buildFinalChunk(event, id, model, created, toolCalls)];
    }

    default: {
      return [];
    }
  }
}

function handleItemAdded(
  event: ResponseOutputItemAddedEvent,
  id: string,
  model: string,
  created: number,
  toolCalls: Map<number, ToolCallAccumulator>,
  isFirstChunk: () => boolean,
): ChatCompletionChunk[] {
  if (event.item.type !== "function_call") return [];

  const accumulator: ToolCallAccumulator = {
    index: event.output_index,
    id: event.item.call_id,
    name: event.item.name,
    arguments: "",
  };
  toolCalls.set(event.output_index, accumulator);

  const chunks: ChatCompletionChunk[] = [];
  if (isFirstChunk()) {
    chunks.push(buildChunk(id, model, created, { role: "assistant" }, null));
  }
  chunks.push(
    buildChunk(id, model, created, {}, null, [
      {
        index: event.output_index,
        id: event.item.call_id,
        type: "function",
        function: { name: event.item.name, arguments: "" },
      },
    ]),
  );
  return chunks;
}

function buildChunk(
  id: string,
  model: string,
  created: number,
  delta: ChatCompletionChunk["choices"][number]["delta"],
  finishReason: ChatCompletionChunk["choices"][number]["finish_reason"],
  toolCalls?: ChatCompletionChunk["choices"][number]["delta"]["tool_calls"],
): ChatCompletionChunk {
  return {
    id,
    object: "chat.completion.chunk",
    created,
    model,
    choices: [
      {
        index: 0,
        delta: toolCalls ? { tool_calls: toolCalls } : delta,
        finish_reason: finishReason,
      },
    ],
  };
}

function buildFinalChunk(
  event: ResponseCompletedEvent,
  id: string,
  model: string,
  created: number,
  toolCalls: Map<number, ToolCallAccumulator>,
): ChatCompletionChunk {
  const hasToolCalls = toolCalls.size > 0;
  const usage = event.response.usage;
  return {
    id,
    object: "chat.completion.chunk",
    created,
    model,
    choices: [
      {
        index: 0,
        delta: {},
        finish_reason: hasToolCalls ? "tool_calls" : "stop",
      },
    ],
    usage: {
      prompt_tokens: usage.input_tokens,
      completion_tokens: usage.output_tokens,
      total_tokens: usage.input_tokens + usage.output_tokens,
    },
  };
}

function ensureToolCall(
  toolCalls: Map<number, ToolCallAccumulator>,
  event: ResponseFunctionCallArgumentsDeltaEvent,
): void {
  if (!toolCalls.has(event.output_index)) {
    toolCalls.set(event.output_index, {
      index: event.output_index,
      id: event.call_id,
      name: event.name,
      arguments: "",
    });
  }
}
