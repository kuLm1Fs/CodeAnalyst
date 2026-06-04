export type CliArgs = {
  gatewayUrl: string;
  maxTokens: number;
  model: string;
  runtime: "mock" | "gateway";
  sessionId: string;
  startGateway: boolean;
  workspace: string;
};

export type AgentPayload = Record<string, unknown>;
export type LocalGatewayAddress = {
  host: string;
  port: string;
};

export function wrapText(text: string, width: number): string[] {
  if (width <= 1) {
    return [text];
  }

  return text.split("\n").flatMap((line) => wrapLine(line, width));
}

export function truncateText(text: string, width: number): string {
  if (width <= 0) {
    return "";
  }

  if (visibleWidth(text) <= width) {
    return text;
  }

  if (width <= 3) {
    return ".".repeat(width);
  }

  return `${sliceVisible(text, width - 3)}...`;
}

export function padRight(text: string, width: number): string {
  const truncated = truncateText(text, width);
  const visible = visibleWidth(truncated);

  return truncated + " ".repeat(Math.max(0, width - visible));
}

export function formatArgsSummary(args: Record<string, unknown>, width = 80): string {
  const pairs = Object.entries(args).map(([key, value]) => `${key}=${formatValue(value)}`);
  return truncateText(pairs.join(" "), width);
}

export function formatAgentEvent(event: string, payload: AgentPayload = {}): string | null {
  if (event === "skills.selected") {
    const skillNames = payload.skill_names;
    if (Array.isArray(skillNames) && skillNames.length > 0) {
      return `Skills: ${skillNames.map(String).join(", ")}`;
    }
    return "Skills: none";
  }

  if (event === "model.request") {
    return `Model request: ${String(payload.model ?? "default")}`;
  }

  if (event === "tool.before") {
    return `Tool starting: ${String(payload.tool_name ?? "unknown")}`;
  }

  if (event === "tool.after") {
    const toolName = String(payload.tool_name ?? "unknown");
    return payload.success === false ? `Tool failed: ${toolName}` : `Tool done: ${toolName}`;
  }

  if (event === "session.end") {
    return "Session complete";
  }

  return null;
}

export function displayRole(role: string): string {
  return role === "assistant" ? "lumak" : role;
}

export function createSessionId(prefix = "tui"): string {
  const cryptoLike = globalThis.crypto;
  if (cryptoLike && "randomUUID" in cryptoLike) {
    return `${prefix}-${cryptoLike.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function parseLocalGatewayUrl(url: string): LocalGatewayAddress | null {
  try {
    const parsed = new URL(url);
    if (!["127.0.0.1", "localhost"].includes(parsed.hostname)) {
      return null;
    }

    return {
      host: parsed.hostname,
      port: parsed.port || "8765",
    };
  } catch {
    return null;
  }
}

export function parseCliArgs(argv: string[]): CliArgs {
  const args: CliArgs = {
    gatewayUrl: process.env.LUMAK_GATEWAY_URL || "ws://127.0.0.1:8765",
    maxTokens: 1024,
    model: process.env.LUMAK_MODEL || "mock-code-agent",
    runtime: "gateway",
    sessionId: createSessionId(),
    startGateway: true,
    workspace: process.cwd(),
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];

    if (arg === "--gateway" && next) {
      args.gatewayUrl = next;
      index += 1;
    } else if (arg === "--max-tokens" && next) {
      args.maxTokens = Number.parseInt(next, 10);
      index += 1;
    } else if (arg === "--model" && next) {
      args.model = next;
      index += 1;
    } else if (arg === "--runtime" && next) {
      args.runtime = next === "gateway" ? "gateway" : "mock";
      index += 1;
    } else if (arg === "--session" && next) {
      args.sessionId = next;
      index += 1;
    } else if (arg === "--workspace" && next) {
      args.workspace = next;
      index += 1;
    } else if (arg === "--no-start-gateway") {
      args.startGateway = false;
    } else if (arg === "--help" || arg === "-h") {
      printHelp();
      process.exit(0);
    }
  }

  if (!Number.isFinite(args.maxTokens) || args.maxTokens <= 0) {
    args.maxTokens = 1024;
  }

  return args;
}

export function printHelp(): void {
  process.stdout.write(`LumaK TypeScript TUI

Usage:
  lumak-tui [options]

Options:
  --gateway <url>        WebSocket gateway URL. Default: ws://127.0.0.1:8765
  --runtime <name>       Runtime adapter: gateway or mock. Default: gateway
  --model <name>         Model label shown in the header. Default: mock-code-agent
  --max-tokens <count>   Maximum model output tokens. Default: 1024
  --session <id>         Session id to use. Default: generated tui-* id
  --workspace <path>     Workspace for the auto-started gateway. Default: cwd
  --no-start-gateway     Connect to an existing gateway only
  -h, --help             Show this help
`);
}

export function visibleWidth(text: string): number {
  let width = 0;
  const stripped = stripAnsi(text);
  for (let index = 0; index < stripped.length; ) {
    const codePoint = stripped.codePointAt(index);
    if (codePoint === undefined) {
      break;
    }
    const char = String.fromCodePoint(codePoint);
    width += charWidth(codePoint);
    index += char.length;
  }
  return width;
}

function wrapLine(line: string, width: number): string[] {
  if (line === "") {
    return [""];
  }

  const lines: string[] = [];
  let current = "";
  for (const word of line.split(/(\s+)/)) {
    if (word === "") {
      continue;
    }
    const candidate = current + word;
    if (visibleWidth(candidate.trimEnd()) <= width) {
      current = candidate;
      continue;
    }

    if (current.trimEnd()) {
      lines.push(current.trimEnd());
      current = word.trimStart();
    }

    while (visibleWidth(current) > width) {
      const chunk = sliceVisible(current, width);
      lines.push(chunk);
      current = current.slice(chunk.length);
    }
  }

  if (current || lines.length === 0) {
    lines.push(current.trimEnd());
  }
  return lines;
}

function sliceVisible(text: string, width: number): string {
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
    const charW = charWidth(codePoint);
    if (visible + charW > width) {
      break;
    }
    output += char;
    visible += charW;
    index += char.length;
  }
  return output;
}

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}

function charWidth(codePoint: number): number {
  if (codePoint === 0 || codePoint < 32 || (codePoint >= 0x7f && codePoint < 0xa0)) {
    return 0;
  }
  if (codePoint >= 0x300 && codePoint <= 0x36f) {
    return 0;
  }
  if (
    codePoint >= 0x1100 && (
      codePoint <= 0x115f ||
      codePoint === 0x2329 ||
      codePoint === 0x232a ||
      (codePoint >= 0x2e80 && codePoint <= 0xa4cf && codePoint !== 0x303f) ||
      (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
      (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
      (codePoint >= 0xfe10 && codePoint <= 0xfe19) ||
      (codePoint >= 0xfe30 && codePoint <= 0xfe6f) ||
      (codePoint >= 0xff00 && codePoint <= 0xff60) ||
      (codePoint >= 0xffe0 && codePoint <= 0xffe6)
    )
  ) {
    return 2;
  }
  return 1;
}

function formatValue(value: unknown): string {
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" || typeof value === "boolean" || value == null) {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => formatValue(item)).join(",")}]`;
  }
  return "{...}";
}
