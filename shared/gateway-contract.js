const todoStatuses = new Set(["pending", "running", "done", "failed"]);
const todoSources = new Set(["runtime", "model"]);

export function normalizeTodoTasks(rawTasks) {
  if (!Array.isArray(rawTasks)) {
    return [];
  }

  return rawTasks.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return [];
    }
    const id = typeof item.id === "string" ? item.id.trim() : "";
    const title = typeof item.title === "string" ? item.title.trim() : "";
    const status = item.status;
    const source = item.source;
    if (!id || !title || !todoStatuses.has(status) || !todoSources.has(source)) {
      return [];
    }

    const task = {
      id,
      title,
      status,
      source,
    };
    if (typeof item.detail === "string" && item.detail.trim()) {
      task.detail = item.detail.trim();
    }
    return [task];
  });
}

export function buildChatPayload(message, sessionId, providerConfig) {
  const payload = {
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

export function buildProjectSwitchPayload(sessionId, path) {
  return {
    type: "project.switch",
    session_id: sessionId,
    path,
  };
}
