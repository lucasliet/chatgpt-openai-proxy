import { describe, expect, it } from "bun:test";
import { convertResponsesToChat } from "../../src/converters/responses-to-chat";
import type { ResponsesResponse } from "../../src/types/responses";

function baseResponse(output: ResponsesResponse["output"]): ResponsesResponse {
  return {
    id: "resp_abc",
    object: "response",
    model: "gpt-5.1-codex",
    output,
    usage: { input_tokens: 150, output_tokens: 45 },
  };
}

describe("convertResponsesToChat", () => {
  it("mapeia output de mensagem para content e finish_reason stop", () => {
    const response = baseResponse([
      {
        type: "message",
        role: "assistant",
        content: [{ type: "output_text", text: "Olá!" }],
      },
    ]);

    const result = convertResponsesToChat(response);

    expect(result.id).toBe("resp_abc");
    expect(result.object).toBe("chat.completion");
    expect(result.model).toBe("gpt-5.1-codex");
    expect(result.choices[0].message.content).toBe("Olá!");
    expect(result.choices[0].message.tool_calls).toBeUndefined();
    expect(result.choices[0].finish_reason).toBe("stop");
  });

  it("retorna content null quando só há function_call", () => {
    const response = baseResponse([
      {
        type: "function_call",
        call_id: "call_xyz",
        name: "get_weather",
        arguments: '{"location":"London"}',
      },
    ]);

    const result = convertResponsesToChat(response);

    expect(result.choices[0].message.content).toBeNull();
    expect(result.choices[0].message.tool_calls).toEqual([
      {
        id: "call_xyz",
        type: "function",
        function: { name: "get_weather", arguments: '{"location":"London"}' },
      },
    ]);
    expect(result.choices[0].finish_reason).toBe("tool_calls");
  });

  it("suporta content + tool_calls simultaneamente", () => {
    const response = baseResponse([
      {
        type: "message",
        role: "assistant",
        content: [{ type: "output_text", text: "Vou verificar." }],
      },
      {
        type: "function_call",
        call_id: "call_1",
        name: "get_weather",
        arguments: "{}",
      },
    ]);

    const result = convertResponsesToChat(response);

    expect(result.choices[0].message.content).toBe("Vou verificar.");
    expect(result.choices[0].message.tool_calls).toHaveLength(1);
    expect(result.choices[0].finish_reason).toBe("tool_calls");
  });

  it("concatena múltiplos output_text em uma única string", () => {
    const response = baseResponse([
      {
        type: "message",
        role: "assistant",
        content: [
          { type: "output_text", text: "Parte 1 " },
          { type: "output_text", text: "Parte 2" },
        ],
      },
    ]);

    expect(convertResponsesToChat(response).choices[0].message.content).toBe("Parte 1 Parte 2");
  });

  it("mapeia usage corretamente (total = input + output)", () => {
    const result = convertResponsesToChat(baseResponse([]));

    expect(result.usage).toEqual({
      prompt_tokens: 150,
      completion_tokens: 45,
      total_tokens: 195,
    });
  });

  it("cria múltiplos tool_calls quando há várias function_calls", () => {
    const response = baseResponse([
      { type: "function_call", call_id: "c1", name: "fn1", arguments: "{}" },
      { type: "function_call", call_id: "c2", name: "fn2", arguments: "{}" },
    ]);

    const result = convertResponsesToChat(response);

    expect(result.choices[0].message.tool_calls).toHaveLength(2);
    expect(result.choices[0].message.tool_calls?.map((t) => t.id)).toEqual(["c1", "c2"]);
  });
});
