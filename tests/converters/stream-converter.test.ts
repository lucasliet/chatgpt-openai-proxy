import { describe, expect, it } from "bun:test";
import { convertResponsesStreamToChat, parseSseEvents } from "../../src/converters/stream-converter";
import type { ResponsesStreamEvent } from "../../src/types/responses";

function sseFrame(event: ResponsesStreamEvent): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function toStream(events: ResponsesStreamEvent[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const content = events.map(sseFrame).join("");
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(content));
      controller.close();
    },
  });
}

async function collectStream(stream: ReadableStream<Uint8Array>): Promise<string[]> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const frames: string[] = [];
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    frames.push(...parts);
  }
  return frames;
}

function parseData(frame: string): string | null {
  const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
  if (!dataLine) return null;
  return dataLine.slice(5).trimStart();
}

function parseJsonFrames(frames: string[]): Record<string, unknown>[] {
  return frames
    .map(parseData)
    .filter((d): d is string => d !== null && d !== "[DONE]")
    .map((d) => JSON.parse(d) as Record<string, unknown>);
}

describe("stream-converter", () => {
  describe("parseSseEvents", () => {
    it("decodifica frames SSE em eventos tipados", async () => {
      const events = [
        { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "Hi" },
      ] as const;
      const parsed: ResponsesStreamEvent[] = [];
      for await (const e of parseSseEvents(toStream([...events]))) parsed.push(e);

      expect(parsed).toHaveLength(1);
      expect(parsed[0]!.type).toBe("response.output_text.delta");
    });

    it("ignora marcador [DONE]", async () => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(c) {
          c.enqueue(encoder.encode("data: [DONE]\n\n"));
          c.close();
        },
      });

      const parsed: ResponsesStreamEvent[] = [];
      for await (const e of parseSseEvents(stream)) parsed.push(e);

      expect(parsed).toHaveLength(0);
    });

    it("ignora JSON malformado sem lançar erro", async () => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(c) {
          c.enqueue(encoder.encode("data: {not json\n\n"));
          c.close();
        },
      });

      const parsed: ResponsesStreamEvent[] = [];
      for await (const e of parseSseEvents(stream)) parsed.push(e);

      expect(parsed).toHaveLength(0);
    });
  });

  describe("convertResponsesStreamToChat", () => {
    it("emite chunk inicial com role assistant antes do primeiro delta de texto", async () => {
      const events: ResponsesStreamEvent[] = [
        { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "Hello" },
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 10, output_tokens: 5 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));

      const first = JSON.parse(parseData(frames[0]!)!);
      expect(first.choices[0].delta).toEqual({ role: "assistant" });
      expect(first.object).toBe("chat.completion.chunk");
    });

    it("converte output_text.delta em delta.content", async () => {
      const events: ResponsesStreamEvent[] = [
        { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "Hello " },
        { type: "response.output_text.delta", output_index: 0, content_index: 0, delta: "world" },
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 10, output_tokens: 5 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));
      const chunks = parseJsonFrames(frames);
      const contents = chunks
        .map((chunk) => (chunk.choices as Record<string, unknown>[])?.[0])
        .map((choice) => ((choice?.delta as Record<string, unknown>)?.content))
        .filter((c): c is string => typeof c === "string");

      expect(contents).toEqual(["Hello ", "world"]);
    });

    it("emite chunk de tool_call com id e name no output_item.added", async () => {
      const events: ResponsesStreamEvent[] = [
        {
          type: "response.output_item.added",
          output_index: 1,
          item: { type: "function_call", call_id: "call_xyz", name: "get_weather", arguments: "" },
        },
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 10, output_tokens: 5 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));
      const chunks = parseJsonFrames(frames);
      const toolCallChunk = chunks.find(
        (c) => (c.choices as Record<string, unknown>[])?.[0] &&
          ((c.choices as Record<string, unknown>[])[0]!.delta as Record<string, unknown>)?.tool_calls,
      )!;

      const toolCall = (
        ((toolCallChunk.choices as Record<string, unknown>[])[0]!.delta as Record<string, unknown>)
          .tool_calls as Record<string, unknown>[]
      )[0]!;
      expect(toolCall).toMatchObject({
        index: 1,
        id: "call_xyz",
        type: "function",
        function: { name: "get_weather", arguments: "" },
      });
    });

    it("acumula argumentos via function_call_arguments.delta", async () => {
      const events: ResponsesStreamEvent[] = [
        {
          type: "response.output_item.added",
          output_index: 1,
          item: { type: "function_call", call_id: "call_1", name: "fn", arguments: "" },
        },
        {
          type: "response.function_call_arguments.delta",
          output_index: 1,
          item_id: "item_1",
          call_id: "call_1",
          name: "fn",
          delta: '{"locati',
        },
        {
          type: "response.function_call_arguments.delta",
          output_index: 1,
          item_id: "item_1",
          call_id: "call_1",
          name: "fn",
          delta: 'on":"London"}',
        },
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 10, output_tokens: 5 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));
      const chunks = parseJsonFrames(frames);
      const argsChunks = chunks.filter((c) => {
        const delta = ((c.choices as Record<string, unknown>[])?.[0]?.delta) as Record<string, unknown> | undefined;
        const toolCalls = delta?.tool_calls as Record<string, unknown>[] | undefined;
        const fn = toolCalls?.[0]?.function as Record<string, unknown> | undefined;
        return fn?.arguments !== undefined && fn?.name === undefined;
      });

      expect(argsChunks).toHaveLength(2);
      const assembled = argsChunks
        .map((c) => {
          const toolCalls = (((c.choices as Record<string, unknown>[])[0]!.delta as Record<string, unknown>).tool_calls as Record<string, unknown>[]);
          return ((toolCalls[0]!.function as Record<string, unknown>).arguments) as string;
        })
        .join("");
      expect(assembled).toBe('{"location":"London"}');
    });

    it("emite chunk final com finish_reason e usage", async () => {
      const events: ResponsesStreamEvent[] = [
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 100, output_tokens: 50 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));
      const last = JSON.parse(parseData(frames[frames.length - 2]!)!);

      expect(last.choices[0].finish_reason).toBe("stop");
      expect(last.usage).toEqual({ prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 });
    });

    it("define finish_reason tool_calls quando houve function calls", async () => {
      const events: ResponsesStreamEvent[] = [
        {
          type: "response.output_item.added",
          output_index: 0,
          item: { type: "function_call", call_id: "c1", name: "fn", arguments: "" },
        },
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 10, output_tokens: 5 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));
      const last = JSON.parse(parseData(frames[frames.length - 2]!)!);

      expect(last.choices[0].finish_reason).toBe("tool_calls");
    });

    it("termina o stream com data: [DONE]", async () => {
      const events: ResponsesStreamEvent[] = [
        {
          type: "response.completed",
          response: {
            id: "resp_1",
            object: "response",
            model: "gpt-5.1-codex",
            output: [],
            usage: { input_tokens: 10, output_tokens: 5 },
          },
        },
      ];

      const frames = await collectStream(convertResponsesStreamToChat(toStream(events), "gpt-5.1-codex"));

      expect(parseData(frames[frames.length - 1]!)).toBe("[DONE]");
    });
  });
});
