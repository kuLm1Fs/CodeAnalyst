export type ProviderConfig = {
  apiKey: string;
  baseUrl?: string;
  model: string;
  provider: string;
  maxTokens?: number;
  maxSteps?: number;
};

export type AttachmentText =
  | {
      content: string;
      kind: "text";
      name: string;
    }
  | {
      kind: "unsupported";
      name: string;
      reason: string;
    };

export type ChatPayload = {
  type: "chat";
  message: string;
  session_id: string;
  max_tokens: number;
  max_steps?: number;
  provider_config?: {
    api_key: string;
    base_url?: string;
    model: string;
    provider: string;
  };
};

export type ProjectRecord = {
  id: string;
  name: string;
  path?: string;
  updatedAt: number;
};

export function buildGatewayUrl(
  location: Pick<Location, "hostname" | "port" | "protocol" | "search">,
  gatewayPort = 8765,
  overrideUrl?: string | null,
): string {
  return buildGatewayUrlCandidates(location, gatewayPort, overrideUrl)[0] ?? "ws://127.0.0.1:8765";
}

export function buildGatewayUrlCandidates(
  location: Pick<Location, "hostname" | "port" | "protocol" | "search">,
  gatewayPort = 8765,
  overrideUrl?: string | null,
): string[] {
  const candidates: string[] = [];
  const addCandidate = (url: string | undefined) => {
    if (url && !candidates.includes(url)) {
      candidates.push(url);
    }
  };

  const cleanOverrideUrl = overrideUrl?.trim();
  if (cleanOverrideUrl?.startsWith("ws://") || cleanOverrideUrl?.startsWith("wss://")) {
    addCandidate(cleanOverrideUrl);
  }

  const gatewayParam = new URLSearchParams(location.search).get("gateway")?.trim();
  if (gatewayParam?.startsWith("ws://") || gatewayParam?.startsWith("wss://")) {
    addCandidate(gatewayParam);
  }

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const localHosts = new Set(["127.0.0.1", "localhost", "::1"]);

  if (localHosts.has(location.hostname)) {
    const host = location.hostname === "::1" ? "[::1]" : location.hostname;
    addCandidate(`${protocol}//${host}:${gatewayPort}`);
    return candidates;
  }

  const codespacesHost = location.hostname.match(/^(.+)-(\d+)\.(app\.github\.dev|githubpreview\.dev)$/);
  if (codespacesHost) {
    addCandidate(`${protocol}//${codespacesHost[1]}-${gatewayPort}.${codespacesHost[3]}`);
  }

  if (location.port) {
    addCandidate(`${protocol}//${location.hostname}:${gatewayPort}`);
  } else {
    addCandidate(`${protocol}//${location.hostname}`);
  }

  return candidates;
}

export function createProjectRecord(
  input: { name: string; path?: string },
  createId: () => string,
  now: () => number = Date.now,
): ProjectRecord {
  const name = input.name.trim() || "未命名项目";
  const path = input.path?.trim();
  const project: ProjectRecord = {
    id: createId(),
    name: name.slice(0, 64),
    updatedAt: now(),
  };

  if (path) {
    project.path = path;
  }

  return project;
}

export function createProjectRecordFromPath(
  path: string,
  createId: () => string,
  now: () => number = Date.now,
): ProjectRecord | null {
  const cleanPath = path.trim();
  if (!cleanPath) {
    return null;
  }

  const segments = cleanPath.split(/[\\/]+/).filter(Boolean);
  const directoryName = segments.at(-1) || cleanPath;
  return createProjectRecord({ name: directoryName, path: cleanPath }, createId, now);
}

export function buildChatPayload(
  message: string,
  sessionId: string,
  providerConfig?: ProviderConfig,
): ChatPayload {
  const payload: ChatPayload = {
    type: "chat",
    message,
    session_id: sessionId,
    max_tokens: providerConfig?.maxTokens ?? 4096,
    max_steps: providerConfig?.maxSteps ?? 12,
  };

  if (providerConfig?.apiKey && providerConfig.model && providerConfig.provider) {
    payload.provider_config = {
      api_key: providerConfig.apiKey,
      model: providerConfig.model,
      provider: providerConfig.provider,
    };
    if (providerConfig.baseUrl) {
      payload.provider_config.base_url = providerConfig.baseUrl;
    }
  }

  return payload;
}

export function buildAttachmentPrompt(text: string, attachments: AttachmentText[]): string {
  const readableAttachments = attachments.filter(
    (attachment): attachment is Extract<AttachmentText, { kind: "text" }> => attachment.kind === "text",
  );
  const unsupportedAttachments = attachments.filter(
    (attachment): attachment is Extract<AttachmentText, { kind: "unsupported" }> =>
      attachment.kind === "unsupported",
  );

  const parts: string[] = [text || "请根据附件内容继续处理。"];

  if (readableAttachments.length > 0) {
    parts.push("", "已附加文件：", "");
    readableAttachments.forEach((attachment, index) => {
      if (index > 0) {
        parts.push("");
      }
      parts.push(`### ${attachment.name}`, "```text", attachment.content, "```");
    });
  }

  if (unsupportedAttachments.length > 0) {
    parts.push("", "### 未读取的附件");
    unsupportedAttachments.forEach((attachment) => {
      parts.push(`- ${attachment.name}：${attachment.reason}`);
    });
  }

  return parts.join("\n");
}

// Re-export the full markdown renderer from the dedicated module
export { renderMarkdown, addCodeCopyButtons } from "./markdown.js";
export { createMarkdownRenderer } from "./markdown.js";
