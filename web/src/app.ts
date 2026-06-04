import {
  buildAttachmentPrompt,
  buildChatPayload,
  buildGatewayUrlCandidates,
  createProjectRecord,
  createProjectRecordFromPath,
  renderMarkdown,
  type AttachmentText,
  type ProjectRecord,
} from "./app-utils";
import {
  customModelOptions,
  modelOptions,
  providerStorageKey,
  type ProviderConfig,
} from "./provider-config";

const assistantAvatarSrc = new URL("../assets/lumak-logo.png", import.meta.url).href;

function getElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) {
    throw new Error(`Required UI element is missing: ${selector}`);
  }

  return element;
}

const fileInput = getElement<HTMLInputElement>("#fileInput");
const attachmentRow = getElement<HTMLDivElement>("#attachmentRow");
const promptInput = getElement<HTMLTextAreaElement>("#promptInput");
const composer = getElement<HTMLFormElement>(".composer");
const messages = getElement<HTMLElement>(".messages");
const providerForm = getElement<HTMLFormElement>("#providerForm");
const providerSelect = getElement<HTMLSelectElement>("#providerSelect");
const apiKeyInput = getElement<HTMLInputElement>("#apiKeyInput");
const baseUrlInput = getElement<HTMLInputElement>("#baseUrlInput");
const modelSelect = getElement<HTMLSelectElement>("#modelSelect");
const customModelField = getElement<HTMLLabelElement>("#customModelField");
const customModelInput = getElement<HTMLInputElement>("#customModelInput");
const maxTokensInput = getElement<HTMLInputElement>("#maxTokensInput");
const maxStepsInput = getElement<HTMLInputElement>("#maxStepsInput");
const providerState = getElement<HTMLSpanElement>("#providerState");
const providerDialog = getElement<HTMLDialogElement>("#providerDialog");
const openProviderDialog = getElement<HTMLButtonElement>("#openProviderDialog");
const closeProviderDialog = getElement<HTMLButtonElement>("#closeProviderDialog");
const gatewayState = getElement<HTMLSpanElement>("#gatewayState");
const liveStatus = getElement<HTMLDivElement>("#liveStatus");
const sessionState = getElement<HTMLSpanElement>("#sessionState");
const sendButton = getElement<HTMLButtonElement>(".send-button");
const newConversationButton = getElement<HTMLButtonElement>("#newConversationButton");
const clearConversationsButton = getElement<HTMLButtonElement>("#clearConversationsButton");
const conversationList = getElement<HTMLElement>("#conversationList");
const projectList = getElement<HTMLElement>("#projectList");
const addProjectButton = getElement<HTMLButtonElement>("#addProjectButton");
const exportConversationButton = getElement<HTMLButtonElement>("#exportConversationButton");
const openDetailsButton = getElement<HTMLButtonElement>("#openDetailsButton");
const detailsDialog = getElement<HTMLDialogElement>("#detailsDialog");
const closeDetailsDialog = getElement<HTMLButtonElement>("#closeDetailsDialog");
const refreshDetailsButton = getElement<HTMLButtonElement>("#refreshDetailsButton");
const detailsState = getElement<HTMLSpanElement>("#detailsState");
const detailsOutput = getElement<HTMLPreElement>("#detailsOutput");

const selectedFiles: File[] = [];
const sessionStorageKey = "lumak.sessionId";
const conversationStorageKey = "lumak.conversations";
const projectStorageKey = "lumak.projects";
const gatewayOverrideStorageKey = "lumak.gatewayUrl";
const gatewayUrls = buildGatewayUrlCandidates(window.location, 8765, window.localStorage.getItem(gatewayOverrideStorageKey));
const reconnectDelayMs = 1600;
const maxReconnectAttempts = 8;

type GatewayMessage =
  | { type: "gateway.ready" }
  | { type: "chat.started"; session_id: string }
  | { type: "chat.response"; session_id: string; answer: string }
  | { type: "agent.event"; event: string; payload?: Record<string, unknown>; session_id: string }
  | { type: "memory.response"; session_id: string; messages: unknown[] }
  | { type: "conversation.list.response"; conversations: { id: string; title: string; updated_at: string; message_count: number }[] }
  | { type: "conversation.response"; session_id: string; messages: unknown[] }
  | { type: "project.switched"; session_id: string; name: string; path: string }
  | { type: "trace.response"; session_id: string; events: unknown[] }
  | { type: "error"; error: string; session_id?: string }
  | { type: "pong" };

type MessageTone = "info" | "error" | "event";
type MessageRole = "assistant" | "user";
type StoredMessage = {
  retryText?: string;
  role: MessageRole;
  text: string;
  tone?: MessageTone;
};
type Conversation = {
  id: string;
  title: string;
  updatedAt: number;
  messages: StoredMessage[];
};

let websocket: WebSocket | null = null;
let reconnectAttempts = 0;
let gatewayUrlIndex = 0;
let pendingMessage: string | null = null;
let lastFailedPrompt: string | null = null;
let waitingForResponse = false;
let sessionId = getOrCreateSessionId();
let conversations = loadConversations();
let projects = loadProjects();
let latestMemory: unknown[] | null = null;
let latestTrace: unknown[] | null = null;

function getOrCreateSessionId(): string {
  const nextSessionId = createSessionId();
  window.localStorage.setItem(sessionStorageKey, nextSessionId);
  return nextSessionId;
}

function createConversation(id = createSessionId(), title = "新对话"): Conversation {
  return {
    id,
    title,
    updatedAt: Date.now(),
    messages: [
      {
        role: "assistant",
        text: "你好，我可以读取项目结构、定位代码、解释模块关系，也可以帮你做小范围修改。",
      },
    ],
  };
}

function createSessionId(): string {
  return window.crypto && "randomUUID" in window.crypto
    ? window.crypto.randomUUID()
    : `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function getDefaultProject(): ProjectRecord {
  return {
    id: "current-workspace",
    name: "Lumak",
    path: "当前本地 workspace",
    updatedAt: Date.now(),
  };
}

function loadProjects(): ProjectRecord[] {
  const rawProjects = window.localStorage.getItem(projectStorageKey);
  if (!rawProjects) {
    return [getDefaultProject()];
  }

  try {
    const parsed = JSON.parse(rawProjects) as ProjectRecord[];
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed;
    }
  } catch {
    window.localStorage.removeItem(projectStorageKey);
  }

  return [getDefaultProject()];
}

function saveProjects(): void {
  window.localStorage.setItem(projectStorageKey, JSON.stringify(projects));
}

function requestProjectSwitch(path: string): void {
  const socket = websocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    appendMessage("Gateway 未连接，暂时不能切换项目 workspace。", "assistant", "error");
    return;
  }

  socket.send(JSON.stringify({ type: "project.switch", session_id: sessionId, path }));
}

function addProjectFromPath(path: string): void {
  const project = createProjectRecordFromPath(path, createSessionId);
  if (!project) {
    return;
  }

  projects = [project, ...projects];
  saveProjects();
  renderProjectList();
  requestProjectSwitch(path);
}

function loadConversations(): Conversation[] {
  const rawConversations = window.localStorage.getItem(conversationStorageKey);
  if (!rawConversations) {
    return [createConversation(sessionId)];
  }

  try {
    const parsed = JSON.parse(rawConversations) as Conversation[];
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed;
    }
  } catch {
    window.localStorage.removeItem(conversationStorageKey);
  }

  return [createConversation(sessionId)];
}

function saveConversations(): void {
  window.localStorage.setItem(conversationStorageKey, JSON.stringify(conversations));
}

function getActiveConversation(): Conversation {
  let conversation = conversations.find((item) => item.id === sessionId);
  if (!conversation) {
    conversation = createConversation(sessionId);
    conversations.unshift(conversation);
    saveConversations();
  }
  return conversation;
}

function setActiveConversation(nextSessionId: string): void {
  sessionId = nextSessionId;
  window.localStorage.setItem(sessionStorageKey, sessionId);
  getActiveConversation();
  updateSessionState();
  renderConversationList();
  renderProjectList();
  renderCurrentConversation();

  const conversation = conversations.find((c) => c.id === nextSessionId);
  if (conversation && conversation.messages.length === 0) {
    websocket?.send(JSON.stringify({ type: "conversation.get", session_id: nextSessionId }));
  }
}

function startNewConversation(): void {
  const activeConversation = getActiveConversation();
  const isEmptyConversation =
    activeConversation.messages.length === 1 &&
    activeConversation.messages[0]?.role === "assistant" &&
    activeConversation.title.startsWith("新对话");

  if (isEmptyConversation) {
    promptInput.focus();
    return;
  }

  const conversation = createConversation();
  const existingNewConversationCount = conversations.filter((item) => item.title.startsWith("新对话")).length;
  conversation.title = existingNewConversationCount === 0 ? "新对话" : `新对话 ${existingNewConversationCount + 1}`;
  conversations = [conversation, ...conversations];
  saveConversations();
  setActiveConversation(conversation.id);
  promptInput.focus();
}

function clearConversations(): void {
  conversations = [createConversation(sessionId)];
  saveConversations();
  renderConversationList();
  renderCurrentConversation();
}

function mergeServerConversations(
  serverSessions: { id: string; title: string; updated_at: string; message_count: number }[],
): void {
  const localIds = new Set(conversations.map((c) => c.id));

  for (const session of serverSessions) {
    if (localIds.has(session.id)) {
      continue;
    }

    conversations.push({
      id: session.id,
      title: session.title || "新对话",
      updatedAt: new Date(session.updated_at).getTime(),
      messages: [],
    });
  }

  saveConversations();
  renderConversationList();
}

function formatRelativeTime(timestamp: number): string {
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (elapsedSeconds < 60) {
    return "刚刚";
  }
  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  if (elapsedMinutes < 60) {
    return `${elapsedMinutes} 分钟前`;
  }
  const elapsedHours = Math.floor(elapsedMinutes / 60);
  if (elapsedHours < 24) {
    return `${elapsedHours} 小时前`;
  }
  const elapsedDays = Math.floor(elapsedHours / 24);
  return `${elapsedDays} 天前`;
}

function maskApiKey(apiKey: string): string {
  if (apiKey.length <= 8) {
    return "已保存";
  }

  return `${apiKey.slice(0, 4)}...${apiKey.slice(-4)}`;
}

function getProviderLabel(provider: string): string {
  return providerSelect.querySelector<HTMLOptionElement>(`option[value="${provider}"]`)?.textContent ?? provider;
}

function setModelOptions(provider: string, selectedModel?: string): void {
  const options = modelOptions[provider] ?? customModelOptions;
  modelSelect.innerHTML = "";

  options.forEach((model) => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model === "custom" ? "Custom model" : model;
    modelSelect.append(option);
  });

  if (selectedModel && options.includes(selectedModel)) {
    modelSelect.value = selectedModel;
  } else if (selectedModel) {
    modelSelect.value = "custom";
    customModelInput.value = selectedModel;
  }

  updateCustomModelVisibility();
}

function updateCustomModelVisibility(): void {
  const needsCustomModel = modelSelect.value === "custom" || providerSelect.value === "custom";
  customModelField.hidden = !needsCustomModel;
}

function renderProviderState(config?: ProviderConfig): void {
  if (!config) {
    providerState.textContent = "未配置";
    return;
  }

  const baseUrlLabel = config.baseUrl ? ` · ${config.baseUrl}` : "";
  const maxTokensLabel = config.maxTokens ? ` · max_tokens=${config.maxTokens}` : "";
  const maxStepsLabel = config.maxSteps ? ` · max_steps=${config.maxSteps}` : "";
  providerState.textContent = `${getProviderLabel(config.provider)} · ${config.model} · ${maskApiKey(config.apiKey)}${baseUrlLabel}${maxTokensLabel}${maxStepsLabel}`;
}

function loadProviderConfig(): void {
  const rawConfig = window.localStorage.getItem(providerStorageKey);
  setModelOptions(providerSelect.value);

  if (!rawConfig) {
    return;
  }

  const config = JSON.parse(rawConfig) as ProviderConfig;
  providerSelect.value = config.provider;
  apiKeyInput.value = config.apiKey;
  baseUrlInput.value = config.baseUrl ?? "";
  maxTokensInput.value = config.maxTokens?.toString() ?? "";
  maxStepsInput.value = config.maxSteps?.toString() ?? "";
  setModelOptions(config.provider, config.model);
  renderProviderState(config);
}

function getProviderConfig(): ProviderConfig | undefined {
  const rawConfig = window.localStorage.getItem(providerStorageKey);
  if (!rawConfig) {
    return undefined;
  }

  try {
    return JSON.parse(rawConfig) as ProviderConfig;
  } catch {
    window.localStorage.removeItem(providerStorageKey);
    return undefined;
  }
}

function renderAttachments(): void {
  attachmentRow.innerHTML = "";
  attachmentRow.hidden = selectedFiles.length === 0;

  selectedFiles.forEach((file) => {
    const chip = document.createElement("div");
    chip.className = "attachment-chip";

    const icon = document.createElement("strong");
    icon.textContent = file.type.startsWith("image/") ? "IMG" : "FILE";

    const name = document.createElement("span");
    name.textContent = file.name;

    chip.append(icon, name);
    attachmentRow.append(chip);
  });
}

function setGatewayState(text: string, state: "connected" | "connecting" | "error"): void {
  gatewayState.textContent = text;
  gatewayState.dataset.state = state;
  gatewayState.title = gatewayUrls[gatewayUrlIndex] ?? gatewayUrls.join("\n");
}

function updateSessionState(): void {
  sessionState.textContent = `Session ${sessionId.slice(0, 8)}`;
}

function setComposerBusy(isBusy: boolean): void {
  waitingForResponse = isBusy;
  promptInput.disabled = isBusy;
  sendButton.disabled = isBusy;
  if (!isBusy) {
    liveStatus.hidden = true;
  }
}

function setLiveStatus(text: string): void {
  liveStatus.textContent = text;
  liveStatus.hidden = false;
}

function addCodeCopyButtons(container: HTMLElement): void {
  container.querySelectorAll<HTMLElement>("pre.code-block").forEach((block) => {
    const button = document.createElement("button");
    button.className = "copy-code-button";
    button.type = "button";
    button.textContent = "复制";
    button.addEventListener("click", async () => {
      const code = block.querySelector("code")?.textContent ?? "";
      await navigator.clipboard.writeText(code);
      button.textContent = "已复制";
      window.setTimeout(() => {
        button.textContent = "复制";
      }, 1200);
    });
    block.append(button);
  });
}

function renderMessage(message: StoredMessage): void {
  const article = document.createElement("article");
  article.className = `message ${message.role}`;
  if (message.tone) {
    article.classList.add(message.tone);
  }

  if (message.role === "assistant") {
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.src = assistantAvatarSrc;
    avatar.alt = "";
    avatar.setAttribute("aria-hidden", "true");
    article.append(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  bubble.innerHTML = renderMarkdown(message.text);
  addCodeCopyButtons(bubble);

  if (message.retryText) {
    const retryButton = document.createElement("button");
    retryButton.className = "retry-button";
    retryButton.type = "button";
    retryButton.textContent = "重试";
    retryButton.addEventListener("click", () => {
      sendChatMessage(message.retryText ?? "");
    });
    bubble.append(retryButton);
  }

  article.append(bubble);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
}

function appendMessage(
  text: string,
  role: MessageRole,
  tone?: MessageTone,
  conversationId = sessionId,
  retryText?: string,
): void {
  let conversation = conversations.find((item) => item.id === conversationId);
  if (!conversation) {
    conversation = createConversation(conversationId);
    conversations.unshift(conversation);
  }

  const message: StoredMessage = { role, text };
  if (tone) {
    message.tone = tone;
  }
  if (retryText) {
    message.retryText = retryText;
  }
  conversation.messages.push(message);
  conversation.updatedAt = Date.now();
  if (role === "user" && conversation.title === "新对话") {
    conversation.title = text.slice(0, 28) || "新对话";
  }

  conversations = [
    conversation,
    ...conversations.filter((item) => item.id !== conversationId),
  ];
  saveConversations();
  renderConversationList();

  if (conversationId === sessionId) {
    renderMessage(message);
  }
}

function renderCurrentConversation(): void {
  messages.innerHTML = "";
  getActiveConversation().messages.forEach(renderMessage);
}

function renderConversationList(): void {
  conversationList.innerHTML = "";

  conversations.forEach((conversation) => {
    const row = document.createElement("div");
    row.className = "history-row";

    const item = document.createElement("button");
    item.className = "history-item";
    item.type = "button";
    if (conversation.id === sessionId) {
      item.classList.add("active");
    }

    const title = document.createElement("span");
    title.textContent = conversation.title;

    const updatedAt = document.createElement("small");
    updatedAt.textContent = formatRelativeTime(conversation.updatedAt);

    item.append(title, updatedAt);
    item.addEventListener("click", () => {
      if (!waitingForResponse) {
        setActiveConversation(conversation.id);
      } else {
        appendMessage("当前回复还在运行，完成后再切换对话。", "assistant", "event");
      }
    });

    const actions = document.createElement("div");
    actions.className = "history-actions";

    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.textContent = "改名";
    renameButton.addEventListener("click", () => {
      const nextTitle = window.prompt("输入新的对话标题", conversation.title)?.trim();
      if (!nextTitle) {
        return;
      }
      conversation.title = nextTitle.slice(0, 48);
      conversation.updatedAt = Date.now();
      saveConversations();
      renderConversationList();
    });

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => {
      conversations = conversations.filter((item) => item.id !== conversation.id);
      if (conversations.length === 0) {
        conversations = [createConversation()];
      }
      if (conversation.id === sessionId) {
        setActiveConversation(conversations[0]?.id ?? createSessionId());
      } else {
        saveConversations();
        renderConversationList();
      }
    });

    actions.append(renameButton, deleteButton);
    row.append(item, actions);
    conversationList.append(row);
  });
}

function renderProjectList(): void {
  projectList.innerHTML = "";

  projects.forEach((project) => {
    const row = document.createElement("div");
    row.className = "history-row";

    const item = document.createElement("button");
    item.className = "history-item";
    item.type = "button";
    if (project.id === "current-workspace") {
      item.classList.add("active");
    }

    const title = document.createElement("span");
    title.textContent = project.name;

    const detail = document.createElement("small");
    detail.textContent = project.path || formatRelativeTime(project.updatedAt);

    item.append(title, detail);
    item.addEventListener("click", () => {
      const pathLabel = project.path ? `（${project.path}）` : "";
      if (project.id === "current-workspace") {
        appendMessage(`当前正在使用 ${project.name}${pathLabel}。`, "assistant", "event");
        return;
      }
      if (project.path) {
        requestProjectSwitch(project.path);
      }
    });

    const actions = document.createElement("div");
    actions.className = "history-actions";

    const renameButton = document.createElement("button");
    renameButton.type = "button";
    renameButton.textContent = "改名";
    renameButton.addEventListener("click", () => {
      const nextName = window.prompt("输入新的项目名称", project.name)?.trim();
      if (!nextName) {
        return;
      }
      project.name = nextName.slice(0, 64);
      project.updatedAt = Date.now();
      saveProjects();
      renderProjectList();
    });
    actions.append(renameButton);

    if (project.id !== "current-workspace") {
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.textContent = "删除";
      deleteButton.addEventListener("click", () => {
        projects = projects.filter((item) => item.id !== project.id);
        if (projects.length === 0) {
          projects = [getDefaultProject()];
        }
        saveProjects();
        renderProjectList();
      });
      actions.append(deleteButton);
    }

    row.append(item, actions);
    projectList.append(row);
  });
}

function exportCurrentConversation(): void {
  const conversation = getActiveConversation();
  const exported = {
    id: conversation.id,
    title: conversation.title,
    exportedAt: new Date().toISOString(),
    messages: conversation.messages,
  };
  const blob = new Blob([JSON.stringify(exported, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeTitle = conversation.title.replace(/[^\w\u4e00-\u9fa5-]+/g, "-").slice(0, 40) || "conversation";
  link.href = url;
  link.download = `${safeTitle}-${conversation.id.slice(0, 8)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatAgentEvent(message: Extract<GatewayMessage, { type: "agent.event" }>): string | null {
  const payload = message.payload ?? {};

  switch (message.event) {
    case "skills.selected": {
      const skillNames = payload.skill_names;
      if (Array.isArray(skillNames) && skillNames.length > 0) {
        return `已加载技能：${skillNames.join("、")}`;
      }
      return "未匹配到本地技能，使用基础 Agent 能力。";
    }
    case "model.request":
      return `正在请求模型：${String(payload.model ?? "default")}`;
    case "tool.before":
      return `准备调用工具：${String(payload.tool_name ?? "unknown")}`;
    case "tool.after": {
      const toolName = String(payload.tool_name ?? "unknown");
      if (payload.dedup) {
        return `工具调用已跳过（重复）：${toolName}`;
      }
      return payload.success === false ? `工具调用失败：${toolName}` : `工具调用完成：${toolName}`;
    }
    case "session.end": {
      const stopReason = String(payload.stop_reason ?? "");
      if (stopReason === "max_steps") {
        return "达到最大步数，任务已结束";
      }
      if (stopReason === "max_tokens") {
        return "响应被截断（超出 max_tokens），请增加 max_tokens 后重试";
      }
      return "任务完成";
    }
    default:
      return null;
  }
}

function handleGatewayMessage(message: GatewayMessage): void {
  if (message.type === "gateway.ready") {
    setGatewayState("Gateway connected", "connected");
    websocket?.send(JSON.stringify({ type: "conversation.list" }));
    flushPendingMessage();
    return;
  }

  if (message.type === "chat.started") {
    setActiveConversation(message.session_id);
    return;
  }

  if (message.type === "agent.event") {
    const eventText = formatAgentEvent(message);
    if (eventText) {
      appendMessage(eventText, "assistant", "event", message.session_id);
    }

    switch (message.event) {
      case "model.request":
        setLiveStatus(`正在请求模型：${String(message.payload?.model ?? "default")}`);
        break;
      case "tool.before":
        setLiveStatus(`正在调用工具：${String(message.payload?.tool_name ?? "unknown")}`);
        break;
      case "tool.after":
        setLiveStatus("等待模型响应...");
        break;
      case "session.end":
        liveStatus.hidden = true;
        break;
    }
    return;
  }

  if (message.type === "chat.response") {
    lastFailedPrompt = null;
    appendMessage(message.answer || "Agent 已完成，但没有返回文本。", "assistant", undefined, message.session_id);
    setComposerBusy(false);
    return;
  }

  if (message.type === "memory.response") {
    latestMemory = message.messages;
    renderDetails();
    return;
  }

  if (message.type === "conversation.list.response") {
    mergeServerConversations(message.conversations);
    return;
  }

  if (message.type === "conversation.response") {
    const existing = conversations.find((c) => c.id === message.session_id);
    if (existing) {
      existing.messages = (message.messages as { role: string; content: string }[]).map(
        (msg) =>
          ({
            role: msg.role,
            text: typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content),
          }) as StoredMessage,
      );
      existing.updatedAt = Date.now();
      saveConversations();
      renderConversationList();
      if (sessionId === message.session_id) {
        renderCurrentConversation();
      }
    }
    return;
  }

  if (message.type === "project.switched") {
    const existingProject = projects.find((project) => project.path === message.path);
    if (existingProject) {
      existingProject.name = message.name;
      existingProject.updatedAt = Date.now();
    } else {
      projects = [
        createProjectRecord({ name: message.name, path: message.path }, () => `workspace-${Date.now()}`),
        ...projects,
      ];
    }
    saveProjects();
    renderProjectList();
    appendMessage(`已切换 workspace：${message.name}\n\n\`${message.path}\``, "assistant", "event", message.session_id);
    return;
  }

  if (message.type === "trace.response") {
    latestTrace = message.events;
    renderDetails();
    return;
  }

  if (message.type === "error") {
    appendMessage(`运行出错：${message.error}`, "assistant", "error", message.session_id ?? sessionId, lastFailedPrompt ?? undefined);
    setComposerBusy(false);
  }
}

function connectGateway(): void {
  setGatewayState("Gateway connecting", "connecting");
  const gatewayUrl = gatewayUrls[gatewayUrlIndex] ?? gatewayUrls[0] ?? "ws://127.0.0.1:8765";
  websocket = new WebSocket(gatewayUrl);

  websocket.addEventListener("open", () => {
    reconnectAttempts = 0;
    setGatewayState("Gateway connected", "connected");
  });

  websocket.addEventListener("message", (event) => {
    try {
      handleGatewayMessage(JSON.parse(String(event.data)) as GatewayMessage);
    } catch (error) {
      appendMessage(`无法解析 gateway 消息：${String(error)}`, "assistant", "error");
      setComposerBusy(false);
    }
  });

  websocket.addEventListener("close", () => {
    websocket = null;
    setGatewayState("Gateway disconnected", "error");
    setComposerBusy(false);

    if (reconnectAttempts >= maxReconnectAttempts) {
      appendMessage(
        [
          "无法连接 gateway。",
          "",
          "已尝试连接：",
          ...gatewayUrls.map((url) => `- \`${url}\``),
          "",
          "请确认 gateway 正在运行，并且 Codespaces 已转发 8765 端口。也可以在页面 URL 后添加 `?gateway=wss://你的-gateway-地址` 手动指定。",
        ].join("\n"),
        "assistant",
        "error",
      );
      return;
    }

    reconnectAttempts += 1;
    gatewayUrlIndex = (gatewayUrlIndex + 1) % gatewayUrls.length;
    window.setTimeout(connectGateway, reconnectDelayMs);
  });

  websocket.addEventListener("error", () => {
    setGatewayState("Gateway error", "error");
  });
}

function sendChatMessage(text: string): void {
  const socket = websocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    pendingMessage = text;
    setGatewayState("Gateway connecting", "connecting");
    if (!socket) {
      connectGateway();
    }
    return;
  }

  pendingMessage = null;
  lastFailedPrompt = text;
  setComposerBusy(true);
  socket.send(JSON.stringify(buildChatPayload(text, sessionId, getProviderConfig())));
}

function flushPendingMessage(): void {
  if (pendingMessage && !waitingForResponse) {
    sendChatMessage(pendingMessage);
  }
}

function resizePrompt(): void {
  promptInput.style.height = "auto";
  promptInput.style.height = `${promptInput.scrollHeight}px`;
}

function requestSessionDetails(): void {
  const socket = websocket;
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    detailsState.textContent = "Gateway 未连接";
    return;
  }

  detailsState.textContent = "加载中";
  socket.send(JSON.stringify({ type: "memory.get", session_id: sessionId }));
  socket.send(JSON.stringify({ type: "trace.get", session_id: sessionId }));
}

function renderDetails(): void {
  detailsState.textContent = "已更新";
  detailsOutput.textContent = JSON.stringify(
    {
      memory: latestMemory ?? [],
      trace: latestTrace ?? [],
    },
    null,
    2,
  );
}

function isReadableTextFile(file: File): boolean {
  if (file.type.startsWith("text/")) {
    return true;
  }

  return /\.(c|css|csv|go|h|html|java|js|json|jsx|log|md|py|rs|sh|sql|ts|tsx|txt|xml|yaml|yml)$/i.test(
    file.name,
  );
}

async function readSelectedAttachments(): Promise<AttachmentText[]> {
  const maxReadableBytes = 180_000;
  return Promise.all(
    selectedFiles.map(async (file) => {
      if (!isReadableTextFile(file)) {
        return {
          kind: "unsupported",
          name: file.name,
          reason: `暂不支持读取 ${file.type || "该文件类型"}`,
        };
      }

      if (file.size > maxReadableBytes) {
        return {
          kind: "unsupported",
          name: file.name,
          reason: "文件超过 180KB，请缩小后再上传",
        };
      }

      return {
        content: await file.text(),
        kind: "text",
        name: file.name,
      };
    }),
  );
}

fileInput.addEventListener("change", () => {
  selectedFiles.splice(0, selectedFiles.length, ...Array.from(fileInput.files ?? []));
  renderAttachments();
});

promptInput.addEventListener("input", resizePrompt);

promptInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
    return;
  }

  event.preventDefault();
  composer.requestSubmit();
});

newConversationButton.addEventListener("click", () => {
  if (waitingForResponse) {
    appendMessage("当前回复还在运行，完成后再新建对话。", "assistant", "event");
    return;
  }

  startNewConversation();
});

clearConversationsButton.addEventListener("click", () => {
  if (window.confirm("确定清空本地历史对话吗？")) {
    clearConversations();
  }
});

addProjectButton.addEventListener("click", () => {
  const path = window.prompt("输入本地项目目录路径，例如 /Users/you/code/project。也可以在该目录启动 gateway 作为默认 WORKSPACE。")?.trim();
  if (path) {
    addProjectFromPath(path);
  }
});

exportConversationButton.addEventListener("click", () => {
  exportCurrentConversation();
});

openDetailsButton.addEventListener("click", () => {
  detailsDialog.showModal();
  requestSessionDetails();
});

closeDetailsDialog.addEventListener("click", () => {
  detailsDialog.close();
});

refreshDetailsButton.addEventListener("click", () => {
  requestSessionDetails();
});

detailsDialog.addEventListener("click", (event) => {
  if (event.target === detailsDialog) {
    detailsDialog.close();
  }
});

openProviderDialog.addEventListener("click", () => {
  providerDialog.showModal();
});

closeProviderDialog.addEventListener("click", () => {
  providerDialog.close();
});

providerDialog.addEventListener("click", (event) => {
  if (event.target === providerDialog) {
    providerDialog.close();
  }
});

providerSelect.addEventListener("change", () => {
  setModelOptions(providerSelect.value);
});

modelSelect.addEventListener("change", () => {
  updateCustomModelVisibility();

  if (modelSelect.value === "custom" && !providerDialog.open) {
    providerDialog.showModal();
    customModelInput.focus();
  }
});

providerForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const apiKey = apiKeyInput.value.trim();
  const baseUrl = baseUrlInput.value.trim();
  const model = modelSelect.value === "custom" ? customModelInput.value.trim() : modelSelect.value;

  const needsBaseUrl = providerSelect.value === "custom" || providerSelect.value === "minimax";
  if (!apiKey || !model || (needsBaseUrl && !baseUrl)) {
    renderProviderState();
    return;
  }

  const config: ProviderConfig = {
    apiKey,
    model,
    provider: providerSelect.value,
  };
  if (baseUrl) {
    config.baseUrl = baseUrl;
  }
  const maxTokens = parseInt(maxTokensInput.value.trim(), 10);
  if (maxTokens > 0) {
    config.maxTokens = maxTokens;
  }
  const maxSteps = parseInt(maxStepsInput.value.trim(), 10);
  if (maxSteps > 0) {
    config.maxSteps = maxSteps;
  }

  window.localStorage.setItem(providerStorageKey, JSON.stringify(config));
  renderProviderState(config);
  providerDialog.close();
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();

  const text = promptInput.value.trim();
  if (!text && selectedFiles.length === 0) {
    return;
  }
  const attachments = await readSelectedAttachments();
  const fileSummary = attachments.length > 0
    ? `（已附加 ${attachments.length} 个文件：${attachments.map((file) => file.name).join("、")}）`
    : "";
  const prompt = attachments.length > 0 ? buildAttachmentPrompt(text, attachments) : text;

  appendMessage(`${text || "已上传文件"}${fileSummary}`, "user");
  promptInput.value = "";
  selectedFiles.length = 0;
  fileInput.value = "";
  renderAttachments();
  resizePrompt();

  sendChatMessage(prompt);
});

loadProviderConfig();
updateSessionState();
renderConversationList();
renderProjectList();
renderCurrentConversation();
connectGateway();
