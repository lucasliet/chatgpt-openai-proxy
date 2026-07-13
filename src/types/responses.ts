import type { ChatContentPart } from "./chat-completions";

export type ResponsesRole = "system" | "user" | "assistant" | "developer" | "tool";

export interface ResponsesInputMessage {
  type: "message";
  role: ResponsesRole;
  content: string | ChatContentPart[];
}

export interface ResponsesFunctionCallOutput {
  type: "function_call_output";
  call_id: string;
  output: string;
}

export type ResponsesInputItem = ResponsesInputMessage | ResponsesFunctionCallOutput;

export interface ResponsesTool {
  type: "function";
  name: string;
  description?: string;
  parameters?: Record<string, unknown>;
}

export interface ResponsesRequest {
  model: string;
  instructions?: string;
  input: ResponsesInputItem[];
  tools?: ResponsesTool[];
  tool_choice?: "auto" | "none" | { type: "function"; name: string };
  parallel_tool_calls?: boolean;
  max_output_tokens?: number;
  temperature?: number;
  top_p?: number;
  stream?: boolean;
  store: false;
}

export interface ResponsesMessageItem {
  type: "message";
  role: "assistant";
  content: { type: "output_text"; text: string }[];
}

export interface ResponsesFunctionCallItem {
  type: "function_call";
  call_id: string;
  name: string;
  arguments: string;
}

export type ResponsesOutputItem = ResponsesMessageItem | ResponsesFunctionCallItem;

export interface ResponsesUsage {
  input_tokens: number;
  output_tokens: number;
}

export interface ResponsesResponse {
  id: string;
  object: "response";
  model: string;
  output: ResponsesOutputItem[];
  usage: ResponsesUsage;
}

export interface ResponseCreatedEvent {
  type: "response.created";
  response: { id: string; status: string };
}

export interface ResponseOutputItemAddedEvent {
  type: "response.output_item.added";
  output_index: number;
  item: ResponsesOutputItem;
}

export interface ResponseOutputTextDeltaEvent {
  type: "response.output_text.delta";
  output_index: number;
  content_index: number;
  delta: string;
}

export interface ResponseFunctionCallArgumentsDeltaEvent {
  type: "response.function_call_arguments.delta";
  output_index: number;
  item_id: string;
  call_id: string;
  name: string;
  delta: string;
}

export interface ResponseFunctionCallArgumentsDoneEvent {
  type: "response.function_call_arguments.done";
  output_index: number;
  item_id: string;
  call_id: string;
  name: string;
  arguments: string;
}

export interface ResponseCompletedEvent {
  type: "response.completed";
  response: ResponsesResponse;
}

export type ResponsesStreamEvent =
  | ResponseCreatedEvent
  | ResponseOutputItemAddedEvent
  | ResponseOutputTextDeltaEvent
  | ResponseFunctionCallArgumentsDeltaEvent
  | ResponseFunctionCallArgumentsDoneEvent
  | ResponseCompletedEvent;
