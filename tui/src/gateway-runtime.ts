import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { parseLocalGatewayUrl, truncateText, type CliArgs } from "./app-utils.js";
import type { AgentEvent, AgentRuntime, AgentStatus, AgentTask, RuntimeUnsubscribe } from "./events.js";
import { SimpleWebSocketClient } from "./websocket-client.js";

type GatewayMessage =
  | { type: "gateway.ready" }
  | { type: "chat.started"; session_id: string }
  | { type: "chat.response"; session_id: string; answer: string }
  | { type: "agent.event"; event: string; payload?: Record<string, unknown>; session_id: string; workspace?: string }
  | { type: "project.switched"; session_id: string; name: string; path: string }
  | { type: "error"; error: string; session_id?: string }
  | { type: "pong" };

export class GatewayAgentRuntime implements AgentRuntime {
  private readonly args: CliArgs;
  private readonly repoRoot: string;
  private listeners = new Set<(event: AgentEvent) => void>();
  private socket: SimpleWebSocketClient | null = null;
  private gateway: ChildProcess | null = null;
  private connected: Promise<SimpleWebSocketClient> | null = null;
  private disposed = false;
  private lastStatus: AgentStatus = "Idle";
  private toolTasks: AgentTask[] = [];

  constructor(args: CliArgs, repoRoot: string) {
    this.args = args;
    this.repoRoot = repoRoot;
  }

  subscribe(listener: (event: AgentEvent) => void): RuntimeUnsubscribe {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async sendMessage(message: string): Promise<void> {
    this.emit({ type: "user_message", id: `user-${Date.now()}`, content: message, timestamp: Date.now() });
    this.emitStatus("Thinking", "Connecting to gateway", undefined, "Queued user prompt");
    this.emit({ type: "thinking_start", label: "Waiting for agent", timestamp: Date.now() });

    try {
      const socket = await this.ensureSocket();
      socket.send(
        JSON.stringify({
          type: "chat",
          session_id: this.args.sessionId,
          message,
          max_tokens: this.args.maxTokens,
        }),
      );
    } catch (error) {
      this.emitError(error instanceof Error ? error.message : String(error));
    }
  }

  dispose(): void {
    this.disposed = true;
    this.listeners.clear();
    this.socket?.close();
    this.gateway?.kill();
  }

  private async ensureSocket(): Promise<SimpleWebSocketClient> {
    if (this.socket) {
      return this.socket;
    }
    if (!this.connected) {
      this.connected = this.connectWithGateway();
    }
    return this.connected;
  }

  private async connectWithGateway(): Promise<SimpleWebSocketClient> {
    try {
      return await this.connectWithRetry(this.args.gatewayUrl, 1);
    } catch {
      this.gateway = this.startGatewayIfLocal();
      return await this.connectWithRetry(this.args.gatewayUrl, 30);
    }
  }

  private startGatewayIfLocal(): ChildProcess | null {
    if (!this.args.startGateway) {
      return null;
    }

    const parsed = parseLocalGatewayUrl(this.args.gatewayUrl);
    if (!parsed) {
      return null;
    }

    this.emitStatus("Thinking", "Starting local gateway", undefined, `Starting gateway on ${parsed.host}:${parsed.port}`);
    const child = spawn(
      "uv",
      ["run", "python", "-m", "gateway.app", "--host", parsed.host, "--port", parsed.port, "--workspace", this.args.workspace],
      {
        cwd: this.repoRoot,
        env: buildGatewayEnvironment(this.args.workspace),
        stdio: ["ignore", "pipe", "pipe"],
      },
    );

    child.stderr?.on("data", (chunk: Uint8Array) => {
      const text = new TextDecoder().decode(chunk).trim();
      if (text && !text.includes("address already in use")) {
        this.emitStatus("Thinking", "Gateway stderr", undefined, truncateText(text, 140));
      }
    });

    return child;
  }

  private async connectWithRetry(url: string, attempts: number): Promise<SimpleWebSocketClient> {
    let lastError: unknown = null;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const socket = await SimpleWebSocketClient.connect(url);
        this.socket = socket;
        socket.onMessage((message) => this.handleRawMessage(message));
        socket.onClose(() => {
          this.socket = null;
          this.connected = null;
          if (!this.disposed) {
            const status = this.lastStatus === "Waiting User" || this.lastStatus === "Idle" ? "Idle" : "Error";
            this.emitStatus(status, "Gateway connection closed", undefined, "Gateway connection closed");
          }
        });
        return socket;
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
    }
    throw lastError instanceof Error ? lastError : new Error(`could not connect to ${url}`);
  }

  private handleRawMessage(rawMessage: string): void {
    try {
      this.handleGatewayMessage(JSON.parse(rawMessage) as GatewayMessage);
    } catch (error) {
      this.emitError(error instanceof Error ? error.message : String(error));
    }
  }

  private handleGatewayMessage(message: GatewayMessage): void {
    if (message.type === "gateway.ready") {
      this.emitStatus("Idle", "Gateway connected", undefined, "Gateway connected");
      return;
    }
    if (message.type === "chat.started") {
      this.emitStatus("Thinking", `Session running: ${message.session_id}`, baseTasks(), "Session started");
      return;
    }
    if (message.type === "chat.response") {
      this.emit({ type: "thinking_end", timestamp: Date.now() });
      this.emit({ type: "assistant_message", id: `assistant-${Date.now()}`, content: message.answer, timestamp: Date.now() });
      this.emitStatus("Waiting User", "Waiting for the next prompt", markAllDone(this.toolTasks), "Response complete");
      return;
    }
    if (message.type === "agent.event") {
      this.handleAgentEvent(message.event, message.payload || {});
      return;
    }
    if (message.type === "project.switched") {
      this.emitStatus("Idle", `Workspace: ${message.name}`, undefined, `Workspace switched to ${message.path}`);
      return;
    }
    if (message.type === "error") {
      this.emitError(message.error);
    }
  }

  private handleAgentEvent(event: string, payload: Record<string, unknown>): void {
    if (event === "skills.selected") {
      const skills = Array.isArray(payload.skill_names) ? payload.skill_names.map(String).join(", ") || "none" : "none";
      this.emitStatus("Thinking", "Selecting skills", baseTasks(), `Skills: ${skills}`);
      return;
    }
    if (event === "model.request") {
      const model = String(payload.model ?? "default");
      this.emit({ type: "thinking_start", label: "Model request", timestamp: Date.now() });
      this.emitStatus("Thinking", `Model request: ${model}`, runningTasks("model"), "Model request sent", model);
      return;
    }
    if (event === "model.response") {
      this.emitStatus("Thinking", "Model responded", runningTasks("tool"), "Model response received");
      return;
    }
    if (event === "tool.before") {
      const id = String(payload.tool_use_id || `tool-${Date.now()}`);
      const name = String(payload.tool_name || "unknown");
      const args = isRecord(payload.tool_input) ? payload.tool_input : {};
      this.toolTasks = runningTasks("tool");
      this.emit({
        type: "tool_call_start",
        id,
        name,
        args,
        timestamp: Date.now(),
      });
      this.emitStatus("Running Tool", `Running ${name}`, this.toolTasks, `Tool started: ${name}`);
      return;
    }
    if (event === "tool.after") {
      const id = String(payload.tool_use_id || `tool-${Date.now()}`);
      const success = payload.success !== false;
      this.emit({
        type: "tool_call_end",
        id,
        status: success ? "success" : "failed",
        resultPreview: truncateText(String(payload.output ?? ""), 500),
        timestamp: Date.now(),
      });
      this.toolTasks = runningTasks("answer");
      this.emitStatus("Thinking", "Processing tool result", this.toolTasks, `Tool ${success ? "success" : "failed"}: ${String(payload.tool_name || id)}`);
      return;
    }
    if (event === "session.end") {
      this.emitStatus("Waiting User", "Finalizing response", markAllDone(this.toolTasks), "Session complete");
      return;
    }
    if (event === "loop.iteration.start") {
      this.emitStatus("Thinking", `Loop iteration ${String(payload.iteration ?? "")}`.trim(), undefined, "Loop iteration started");
    }
  }

  private emit(event: AgentEvent): void {
    if (this.disposed) {
      return;
    }
    for (const listener of this.listeners) {
      listener(event);
    }
  }

  private emitError(message: string): void {
    this.emit({ type: "thinking_end", timestamp: Date.now() });
    this.emit({ type: "error", id: `error-${Date.now()}`, message, timestamp: Date.now() });
    this.emitStatus("Error", "Recovered from gateway error", undefined, message);
  }

  private emitStatus(status: AgentStatus, currentStep: string, tasks?: AgentTask[], log?: string, model?: string): void {
    this.lastStatus = status;
    this.emit({
      type: "status_update",
      status,
      model,
      currentStep,
      tasks,
      metrics: {
        tokens: "--",
        cost: "--",
        latency: "--",
        git: "--",
      },
      log,
      timestamp: Date.now(),
    });
  }
}

export function buildGatewayEnvironment(
  workspace: string,
  baseEnv: Record<string, string | undefined> = process.env,
  readText: (path: string) => string | null = readOptionalText,
): Record<string, string | undefined> {
  const env = { ...baseEnv };
  const dotenv = readText(join(workspace, ".env"));
  if (!dotenv) {
    return env;
  }

  for (const [key, value] of parseDotenv(dotenv)) {
    if (!env[key]) {
      env[key] = value;
    }
  }
  return env;
}

function readOptionalText(path: string): string | null {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

function parseDotenv(text: string): Array<[string, string]> {
  const entries: Array<[string, string]> = [];
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) {
      continue;
    }
    const [rawKey, ...rawValue] = line.split("=");
    const key = rawKey.trim();
    const value = rawValue.join("=").trim().replace(/^(['"])(.*)\1$/, "$2");
    if (key) {
      entries.push([key, value]);
    }
  }
  return entries;
}

function baseTasks(): AgentTask[] {
  return [
    { id: "model", title: "Ask model", status: "pending" },
    { id: "tool", title: "Run tools", status: "pending" },
    { id: "answer", title: "Compose answer", status: "pending" },
  ];
}

function runningTasks(active: "model" | "tool" | "answer"): AgentTask[] {
  return baseTasks().map((task) => {
    if (task.id === active) {
      return { ...task, status: "running" };
    }
    if (active === "tool" && task.id === "model") {
      return { ...task, status: "done" };
    }
    if (active === "answer" && task.id !== "answer") {
      return { ...task, status: "done" };
    }
    return task;
  });
}

function markAllDone(tasks: AgentTask[]): AgentTask[] {
  const source = tasks.length > 0 ? tasks : baseTasks();
  return source.map((task) => ({ ...task, status: "done" }));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
