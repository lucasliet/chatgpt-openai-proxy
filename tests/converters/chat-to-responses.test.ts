import { describe, expect, it } from "bun:test";
import { convertChatToResponses } from "../../src/converters/chat-to-responses";
import type { ChatCompletionRequest } from "../../src/types/chat-completions";

describe("convertChatToResponses", () => {
  describe("instructions", () => {
    it("extrai mensagem system para o campo instructions", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [
          { role: "system", content: "You are a coding assistant." },
          { role: "user", content: "Hi" },
        ],
      };

      const result = convertChatToResponses(request);

      expect(result.instructions).toBe("You are a coding assistant.");
      expect(result.input.every((item) => item.type !== "message" || item.role !== "system")).toBe(true);
    });

    it("concatena múltiplas mensagens system com \\\n\\\n", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [
          { role: "system", content: "Regra 1." },
          { role: "system", content: "Regra 2." },
          { role: "user", content: "ok" },
        ],
      };

      expect(convertChatToResponses(request).instructions).toBe("Regra 1.\n\nRegra 2.");
    });

    it("aplica fallback quando não há system message (Codex rejeita vazio)", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "Hi" }],
      };

      expect(convertChatToResponses(request).instructions).toBe("You are a helpful assistant.");
    });

    it("trata developer role como instructions", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [
          { role: "developer", content: "Dev instruction." },
          { role: "user", content: "Hi" },
        ],
      };

      expect(convertChatToResponses(request).instructions).toBe("Dev instruction.");
    });
  });

  describe("input", () => {
    it("mantém mensagens user e assistant no input", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [
          { role: "user", content: "Pergunta" },
          { role: "assistant", content: "Resposta" },
        ],
      };

      const result = convertChatToResponses(request);

      expect(result.input).toEqual([
        { type: "message", role: "user", content: "Pergunta" },
        { type: "message", role: "assistant", content: "Resposta" },
      ]);
    });

    it("converte tool message em function_call_output com call_id", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [
          { role: "user", content: "clima?" },
          { role: "tool", tool_call_id: "call_abc", content: '{"temp":22}' },
        ],
      };

      const result = convertChatToResponses(request);

      expect(result.input).toContainEqual({
        type: "function_call_output",
        call_id: "call_abc",
        output: '{"temp":22}',
      });
    });

    it("preserva content array com image_url", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [
          {
            role: "user",
            content: [
              { type: "text", text: "What is this?" },
              { type: "image_url", image_url: { url: "data:image/png;base64,abc" } },
            ],
          },
        ],
      };

      const result = convertChatToResponses(request);
      const message = result.input[0];

      expect(message).toEqual({
        type: "message",
        role: "user",
        content: [
          { type: "text", text: "What is this?" },
          { type: "image_url", image_url: { url: "data:image/png;base64,abc" } },
        ],
      });
    });
  });

  describe("tools", () => {
    it("achata tools[].function.{name,parameters} para tools[].{name,parameters}", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "clima" }],
        tools: [
          {
            type: "function",
            function: {
              name: "get_weather",
              description: "Get weather",
              parameters: { type: "object", properties: { location: { type: "string" } } },
            },
          },
        ],
      };

      expect(convertChatToResponses(request).tools).toEqual([
        {
          type: "function",
          name: "get_weather",
          description: "Get weather",
          parameters: { type: "object", properties: { location: { type: "string" } } },
        },
      ]);
    });
  });

  describe("parâmetros escalares", () => {
    it("sempre inclui store: false", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "hi" }],
      };

      expect(convertChatToResponses(request).store).toBe(false);
    });

    it("mapeia max_tokens para max_output_tokens", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "hi" }],
        max_tokens: 512,
      };

      expect(convertChatToResponses(request).max_output_tokens).toBe(512);
    });

    it("mapeia max_completion_tokens para max_output_tokens", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "hi" }],
        max_completion_tokens: 1024,
      };

      expect(convertChatToResponses(request).max_output_tokens).toBe(1024);
    });

    it("repassa temperature, top_p e stream", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "hi" }],
        temperature: 0.5,
        top_p: 0.9,
        stream: true,
      };

      const result = convertChatToResponses(request);

      expect(result.temperature).toBe(0.5);
      expect(result.top_p).toBe(0.9);
      expect(result.stream).toBe(true);
    });

    it("mapeia tool_choice de função nomeada", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "hi" }],
        tool_choice: { type: "function", function: { name: "get_weather" } },
      };

      expect(convertChatToResponses(request).tool_choice).toEqual({
        type: "function",
        name: "get_weather",
      });
    });

    it("repassa tool_choice string (auto/none)", () => {
      const request: ChatCompletionRequest = {
        model: "gpt-5.1-codex",
        messages: [{ role: "user", content: "hi" }],
        tool_choice: "auto",
      };

      expect(convertChatToResponses(request).tool_choice).toBe("auto");
    });
  });
});
