import { emitKeypressEvents } from "node:readline";

import { formatArgsSummary, truncateText, visibleWidth, wrapText } from "./app-utils.js";
import type { AgentEvent, AgentRuntime, AgentStatus, AgentTask, RuntimeMetrics, ToolStatus } from "./events.js";

type ChatLine =
  | { kind: "message"; role: "you" | "lumaK" | "system"; content: string }
  | { kind: "tool"; id: string; name: string; args: Record<string, unknown>; status: ToolStatus; resultPreview?: string }
  | { kind: "error"; content: string };

type TerminalUiOptions = {
  projectName: string;
  model: string;
  workspace: string;
};

const CLEAR = "\x1b[2J\x1b[H";
const ALT_SCREEN = "\x1b[?1049h";
const MAIN_SCREEN = "\x1b[?1049l";
const HIDE_CURSOR = "\x1b[?25l";
const SHOW_CURSOR = "\x1b[?25h";
const DISABLE_WRAP = "\x1b[?7l";
const ENABLE_WRAP = "\x1b[?7h";
const CLEAR_LINE = "\x1b[2K";

const color = {
  dim: (text: string) => `\x1b[90m${text}\x1b[0m`,
  bold: (text: string) => `\x1b[1m${text}\x1b[0m`,
  cyan: (text: string) => `\x1b[36m${text}\x1b[0m`,
  green: (text: string) => `\x1b[32m${text}\x1b[0m`,
  yellow: (text: string) => `\x1b[33m${text}\x1b[0m`,
  red: (text: string) => `\x1b[31m${text}\x1b[0m`,
};

export class TerminalUi {
  private readonly runtime: AgentRuntime;
  private readonly options: TerminalUiOptions;
  private readonly unsubscribe: () => void;
  private chat: ChatLine[] = [];
  private logs: string[] = [];
  private tasks: AgentTask[] = [];
  private metrics: RuntimeMetrics = { tokens: "--", cost: "--", latency: "--", git: "--" };
  private model: string;
  private status: AgentStatus = "Idle";
  private currentStep = "Ready";
  private input = "";
  private chatScrollOffset = 0;
  private stopped = false;

  constructor(runtime: AgentRuntime, options: TerminalUiOptions) {
    this.runtime = runtime;
    this.options = options;
    this.model = options.model;
    this.unsubscribe = runtime.subscribe((event) => this.handleEvent(event));
  }

  start(): void {
    process.stdout.write(`${ALT_SCREEN}${DISABLE_WRAP}`);
    emitKeypressEvents(process.stdin);
    if (process.stdin.isTTY) {
      process.stdin.setRawMode(true);
    }
    process.stdin.setEncoding("utf8");
    process.stdin.resume();
    process.stdin.on("keypress", this.onKeypress);
    process.stdout.on("resize", this.render);
    process.on("SIGINT", () => this.stop());
    process.on("SIGTERM", () => this.stop());
    this.pushSystem("LumaK code-agent TUI started. Type /help for commands.");
    this.render();
  }

  stop(): void {
    if (this.stopped) {
      return;
    }
    this.stopped = true;
    this.unsubscribe();
    this.runtime.dispose();
    process.stdin.off("keypress", this.onKeypress);
    process.stdout.off("resize", this.render);
    if (process.stdin.isTTY) {
      process.stdin.setRawMode(false);
    }
    process.stdout.write(`${ENABLE_WRAP}${MAIN_SCREEN}`);
    process.exit(0);
  }

  private readonly onKeypress = (chunkValue: unknown, keyValue?: unknown) => {
    const chunk = typeof chunkValue === "string" ? chunkValue : "";
    const key = isKeypress(keyValue) ? keyValue : undefined;
    if (key?.ctrl && key.name === "c") {
      this.stop();
      return;
    }
    if (key?.name === "return") {
      void this.submitInput();
      return;
    }
    if (key?.name === "up" || key?.name === "pageup") {
      this.scrollChat(key.name === "pageup" ? 8 : 1);
      return;
    }
    if (key?.name === "down" || key?.name === "pagedown") {
      this.scrollChat(key.name === "pagedown" ? -8 : -1);
      return;
    }
    if (key?.name === "home") {
      this.chatScrollOffset = Number.MAX_SAFE_INTEGER;
      this.render();
      return;
    }
    if (key?.name === "end") {
      this.chatScrollOffset = 0;
      this.render();
      return;
    }
    if (key?.name === "backspace") {
      this.input = this.input.slice(0, -1);
      this.render();
      return;
    }
    if (key?.ctrl && key.name === "u") {
      this.input = "";
      this.render();
      return;
    }
    if (!key?.ctrl && chunk && chunk >= " " && chunk !== "\x7f") {
      this.input += chunk;
      this.render();
    }
  };

  private async submitInput(): Promise<void> {
    const text = this.input.trim();
    this.input = "";
    if (!text) {
      this.render();
      return;
    }

    if (text === "/exit" || text === "/quit") {
      this.stop();
      return;
    }
    if (text === "/clear") {
      this.chat = [];
      this.logs = [];
      this.chatScrollOffset = 0;
      this.pushSystem("Screen cleared.");
      this.render();
      return;
    }
    if (text === "/help") {
      this.pushSystem("Commands: /help show commands, /clear clear chat and logs, /exit leave the TUI. Enter submits, Ctrl+C exits. Scroll chat with Up/Down, PageUp/PageDown, Home/End.");
      this.render();
      return;
    }

    try {
      this.chatScrollOffset = 0;
      await this.runtime.sendMessage(text);
    } catch (error) {
      if (!this.stopped) {
        this.handleEvent({
          type: "error",
          id: `error-${Date.now()}`,
          message: error instanceof Error ? error.message : String(error),
          timestamp: Date.now(),
        });
      }
    }
  }

  private handleEvent(event: AgentEvent): void {
    if (event.type === "user_message") {
      this.chatScrollOffset = 0;
      this.chat.push({ kind: "message", role: "you", content: event.content });
    } else if (event.type === "assistant_message") {
      this.chatScrollOffset = 0;
      this.chat.push({ kind: "message", role: "lumaK", content: event.content });
    } else if (event.type === "thinking_start") {
      this.status = "Thinking";
      this.currentStep = event.label || "Thinking";
      this.addLog(this.currentStep);
    } else if (event.type === "thinking_end") {
      this.addLog("Thinking finished");
    } else if (event.type === "tool_call_start") {
      this.status = "Running Tool";
      this.currentStep = `Running ${event.name}`;
      this.chatScrollOffset = 0;
      this.chat.push({ kind: "tool", id: event.id, name: event.name, args: event.args, status: "running" });
      this.addLog(`Tool started: ${event.name}`);
    } else if (event.type === "tool_call_end") {
      const block = this.chat.find((item) => item.kind === "tool" && item.id === event.id);
      if (block?.kind === "tool") {
        block.status = event.status;
        block.resultPreview = event.resultPreview;
      }
      this.addLog(`Tool ${event.status}: ${event.id}`);
    } else if (event.type === "error") {
      this.status = "Error";
      this.currentStep = "Recovered from error";
      this.chatScrollOffset = 0;
      this.chat.push({ kind: "error", content: event.message });
      this.addLog(`Error: ${event.message}`);
    } else if (event.type === "status_update") {
      this.status = event.status;
      this.model = event.model || this.model;
      this.currentStep = event.currentStep || this.currentStep;
      this.tasks = event.tasks || this.tasks;
      this.metrics = event.metrics || this.metrics;
      if (event.log) {
        this.addLog(event.log);
      }
    }
    this.render();
  }

  private render = (): void => {
    if (this.stopped) {
      return;
    }
    const width = Math.max(50, process.stdout.columns || 88);
    const height = Math.max(18, process.stdout.rows || 28);

    const header = this.renderHeader(width);
    const input = this.renderInput(width);
    const bodyHeight = Math.max(5, height - header.length - input.length);
    const body = this.renderChat(width, bodyHeight);

    const screen = [...header, ...body, ...input].slice(0, height).map((line) => fitColumn(line, width));
    while (screen.length < height) {
      screen.push("");
    }

    // Move cursor to input position (IME needs this anchor)
    const inputRow = height; // 1-based
    const promptStr = "❯ ";
    const promptCol = visibleWidth(promptStr);
    const cursorCol = promptCol + visibleWidth(this.input) + 1;
    const cursorMove = `\x1b[${inputRow};${cursorCol}H`;
    const screenOutput = `${CLEAR}${screen.map((line) => `${CLEAR_LINE}${line}`).join("\n")}${cursorMove}`;
    process.stdout.write(screenOutput);
  };

  private renderHeader(width: number): string[] {
    const status = this.status;
    const indicator = runtimeIndicator(status);
    return [
      color.dim(` ${this.options.projectName} (${this.model}) ${indicator}`),
      color.dim("─".repeat(width)),
    ];
  }

  private renderInput(width: number): string[] {
    return renderInputFrame(this.input, this.status, width);
  }

  private renderChat(width: number, height: number): string[] {
    const lines: string[] = [];
    if (this.chat.length === 0) {
      lines.push(color.dim("No messages yet."));
    }
    for (const item of this.chat) {
      if (item.kind === "message") {
        lines.push(...renderMessageBox(item, width));
        lines.push("");
      } else if (item.kind === "tool") {
        lines.push(...renderToolInline(item, width));
      } else {
        lines.push(...renderErrorLine(item.content, width));
        lines.push("");
      }
    }
    this.chatScrollOffset = Math.min(this.chatScrollOffset, Math.max(0, lines.length - height));
    return viewport(lines, height, this.chatScrollOffset);
  }

  private pushSystem(content: string): void {
    this.chat.push({ kind: "message", role: "system", content });
  }

  private addLog(line: string): void {
    this.logs.push(line);
    this.logs = this.logs.slice(-8);
  }

  private scrollChat(delta: number): void {
    this.chatScrollOffset = Math.max(0, this.chatScrollOffset + delta);
    this.render();
  }
}

function isKeypress(value: unknown): value is { name?: string; ctrl?: boolean; sequence?: string } {
  return typeof value === "object" && value !== null;
}

function viewport(lines: string[], height: number, scrollOffset: number): string[] {
  const maxOffset = Math.max(0, lines.length - height);
  const offset = Math.min(scrollOffset, maxOffset);
  const end = Math.max(height, lines.length - offset);
  const visible = lines.slice(Math.max(0, end - height), end);
  while (visible.length < height) {
    visible.push("");
  }
  return visible;
}

export function renderToolInline(item: Extract<ChatLine, { kind: "tool" }>, width: number): string[] {
  const statusDot = toolStatusDot(item.status);
  const argsSummary = formatArgsSummary(item.args, width - 10);
  const line = `  ${statusDot} ${color.dim(item.name)} ${color.dim(argsSummary)}`;
  return [fitColumn(line, width)];
}

export function renderMessageBox(item: Extract<ChatLine, { kind: "message" }>, width: number): string[] {
  const roleLabel = messageRoleLabel(item.role);
  const contentLines = wrapText(renderTerminalMarkdown(item.content), Math.max(8, width - 2));
  const lines = [
    roleLabel,
    ...contentLines.map((line) => `  ${line}`),
  ];

  if (item.role === "system") {
    return lines.map((line) => color.dim(line));
  }
  return lines;
}

export function renderErrorLine(content: string, width: number): string[] {
  return [`  ${color.red("error")} ${content}`];
}

export function renderTerminalMarkdown(text: string): string {
  return text
    .split("\n")
    .map((line) => renderInlineMarkdown(line))
    .join("\n");
}

function renderInlineMarkdown(text: string): string {
  let output = "";
  for (let index = 0; index < text.length; ) {
    if (text[index] === "`") {
      const end = text.indexOf("`", index + 1);
      if (end === -1) {
        output += text.slice(index);
        break;
      }
      output += text.slice(index, end + 1);
      index = end + 1;
      continue;
    }

    if (text.startsWith("**", index)) {
      const end = text.indexOf("**", index + 2);
      if (end > index + 2) {
        output += `\x1b[1m${text.slice(index + 2, end)}\x1b[22m`;
        index = end + 2;
        continue;
      }
    }

    const codePoint = text.codePointAt(index);
    if (codePoint === undefined) {
      break;
    }
    const char = String.fromCodePoint(codePoint);
    output += char;
    index += char.length;
  }
  return output;
}

export function renderInputFrame(input: string, status: AgentStatus, width: number): string[] {
  const prompt = "❯ ";
  const busyText = status === "Thinking" || status === "Running Tool" ? color.dim("  [busy]") : "";
  const busyWidth = visibleLength(busyText);
  const promptWidth = visibleLength(prompt);
  const available = Math.max(1, width - promptWidth - busyWidth);
  const truncatedInput = truncateToWidth(input, available);
  return [
    color.dim("─".repeat(width)),
    `${prompt}${truncatedInput}${busyText}`,
  ];
}

function truncateToWidth(text: string, maxWidth: number): string {
  if (visibleLength(text) <= maxWidth) {
    return text;
  }
  let result = "";
  let width = 0;
  for (const char of text) {
    const charW = charWidth(char);
    if (width + charW > maxWidth) {
      break;
    }
    result += char;
    width += charW;
  }
  return result;
}

function runtimeIndicator(status: AgentStatus): string {
  if (status === "Thinking" || status === "Running Tool") {
    return color.green("●");
  }
  if (status === "Error") {
    return color.red("●");
  }
  return color.dim("●");
}

function toolStatusDot(status: ToolStatus): string {
  if (status === "running") {
    return color.green("●");
  }
  if (status === "failed") {
    return color.red("●");
  }
  return color.dim("●");
}

function messageRoleLabel(role: Extract<ChatLine, { kind: "message" }>["role"]): string {
  if (role === "lumaK") {
    return color.green("lumaK");
  }
  if (role === "you") {
    return color.cyan("you");
  }
  return color.dim("system");
}

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

function visibleLength(text: string): number {
  return visibleWidth(stripAnsi(text));
}

function fitColumn(text: string, width: number): string {
  const truncated = truncateVisible(text, width);
  return `${truncated}${" ".repeat(Math.max(0, width - visibleLength(truncated)))}`;
}

function truncateVisible(text: string, width: number): string {
  if (visibleLength(text) <= width) {
    return text;
  }
  if (width <= 3) {
    return ".".repeat(Math.max(0, width));
  }

  let output = "";
  let visible = 0;
  for (let index = 0; index < text.length; ) {
    const ansi = /^\x1b\[[0-9;]*m/.exec(text.slice(index));
    if (ansi) {
      output += ansi[0];
      index += ansi[0].length;
      continue;
    }

    const codePoint = text.codePointAt(index);
    if (codePoint === undefined) {
      break;
    }
    const char = String.fromCodePoint(codePoint);
    const nextWidth = charWidth(char);
    if (visible + nextWidth > width - 3) {
      break;
    }
    output += char;
    visible += nextWidth;
    index += char.length;
  }
  return `${output}\x1b[0m...`;
}

function charWidth(char: string): number {
  return visibleWidth(char);
}
