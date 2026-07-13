export type ChatRole = "system" | "developer" | "user" | "assistant" | "tool";

export interface ChatTextPart {
  type: "text";
  text: string;
}

export interface ChatImagePart {
  type: "image_url";
  image_url: { url: string };
}

export type ChatContentPart = ChatTextPart | ChatImagePart;

export interface ChatFunctionCall {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

export interface ChatMessage {
  role: ChatRole;
  content: string | ChatContentPart[] | null;
  tool_calls?: ChatFunctionCall[];
  tool_call_id?: string;
  name?: string;
}

export interface ChatToolFunction {
  name: string;
  description?: string;
  parameters?: Record<string, unknown>;
}

export interface ChatTool {
  type: "function";
  function: ChatToolFunction;
}

export interface ChatCompletionRequest {
  model: string;
  messages: ChatMessage[];
  tools?: ChatTool[];
  tool_choice?: "auto" | "none" | { type: "function"; function: { name: string } };
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  max_completion_tokens?: number;
  stream?: boolean;
  stop?: string | string[];
  user?: string;
}

export interface ChatCompletionResponse {
  id: string;
  object: "chat.completion";
  created: number;
  model: string;
  choices: [
    {
      index: number;
      message: {
        role: "assistant";
        content: string | null;
        tool_calls?: ChatFunctionCall[];
      };
      finish_reason: "stop" | "length" | "tool_calls" | "content_filter";
    },
  ];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ChatCompletionDelta {
  role?: "assistant";
  content?: string;
  tool_calls?: [
    {
      index: number;
      id?: string;
      type?: "function";
      function: { name?: string; arguments?: string };
    },
  ];
}

export interface ChatCompletionChunk {
  id: string;
  object: "chat.completion.chunk";
  created: number;
  model: string;
  choices: [
    {
      index: number;
      delta: ChatCompletionDelta;
      finish_reason: "stop" | "length" | "tool_calls" | "content_filter" | null;
    },
  ];
  usage?:
    | {
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
      }
    | null;
}
