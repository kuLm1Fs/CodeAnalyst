export type ProviderConfig = {
  apiKey: string;
  baseUrl?: string;
  model: string;
  provider: string;
  maxTokens?: number;
  maxSteps?: number;
};

export type ChatPayload = {
  type: "chat";
  message: string;
  session_id: string;
  max_tokens: number;
  max_steps: number;
  provider_config?: {
    api_key: string;
    base_url?: string;
    model: string;
    provider: string;
  };
};

export type ProjectSwitchPayload = {
  type: "project.switch";
  session_id: string;
  path: string;
};

export type TodoTaskStatus = "pending" | "running" | "done" | "failed";
export type TodoTaskSource = "runtime" | "model";

export type TodoTask = {
  detail?: string;
  id: string;
  source: TodoTaskSource;
  status: TodoTaskStatus;
  title: string;
};

export type AgentEventMessage = {
  type: "agent.event";
  event: string;
  payload?: Record<string, unknown>;
  session_id: string;
  workspace?: string;
};

export type ProjectRecordMessage = {
  id: string;
  name: string;
  path: string;
  active: boolean;
};

export type ProjectDetailMessage = ProjectRecordMessage & {
  memory_root: string;
  trace_root: string;
  skills_root: string;
};

export type GatewayMessage =
  | { type: "gateway.ready" }
  | { type: "chat.started"; session_id: string }
  | { type: "chat.response"; session_id: string; answer: string }
  | { type: "todo.updated"; session_id: string; tasks: unknown[] }
  | AgentEventMessage
  | { type: "memory.response"; session_id: string; messages: unknown[] }
  | { type: "conversation.list.response"; conversations: unknown[] }
  | { type: "conversation.response"; session_id: string; messages: unknown[] }
  | { type: "project.list.response"; projects: ProjectRecordMessage[] }
  | { type: "project.response"; project: ProjectDetailMessage }
  | { type: "project.switched"; session_id: string; name: string; path: string }
  | { type: "trace.response"; session_id: string; events: unknown[] }
  | { type: "workspace.configured"; name: string; path: string }
  | { type: "error"; error: string; session_id?: string }
  | { type: "pong" };

export function normalizeTodoTasks(rawTasks: unknown): TodoTask[];
export function buildChatPayload(
  message: string,
  sessionId: string,
  providerConfig?: ProviderConfig,
): ChatPayload;
export function buildProjectSwitchPayload(sessionId: string, path: string): ProjectSwitchPayload;
