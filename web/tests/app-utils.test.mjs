import assert from "node:assert/strict";
import test from "node:test";

import {
  buildChatPayload,
  buildAttachmentPrompt,
  buildGatewayUrl,
  buildGatewayUrlCandidates,
  createProjectRecord,
  createProjectRecordFromPath,
  renderMarkdown,
} from "../dist/app-utils.js";

test("buildChatPayload includes provider config when api key and model are present", () => {
  const providerConfig = {
    apiKey: "sk-test",
    baseUrl: "https://example.test/v1",
    model: "gpt-test",
    provider: "openai",
  };

  assert.deepEqual(buildChatPayload("hello", "session-1", providerConfig), {
    type: "chat",
    message: "hello",
    session_id: "session-1",
    max_tokens: 4096,
    max_steps: 12,
    provider_config: {
      api_key: "sk-test",
      base_url: "https://example.test/v1",
      model: "gpt-test",
      provider: "openai",
    },
  });
});

test("buildGatewayUrl uses localhost for local development", () => {
  assert.equal(
    buildGatewayUrl({
      hostname: "127.0.0.1",
      port: "4173",
      protocol: "http:",
      search: "",
    }),
    "ws://127.0.0.1:8765",
  );
});

test("buildGatewayUrl maps Codespaces forwarded web port to gateway port", () => {
  assert.equal(
    buildGatewayUrl({
      hostname: "silver-space-codex-4173.app.github.dev",
      port: "",
      protocol: "https:",
      search: "",
    }),
    "wss://silver-space-codex-8765.app.github.dev",
  );
});

test("buildGatewayUrl supports an explicit query override", () => {
  assert.equal(
    buildGatewayUrl({
      hostname: "silver-space-codex-4173.app.github.dev",
      port: "",
      protocol: "https:",
      search: "?gateway=wss%3A%2F%2Fcustom-gateway.example.test",
    }),
    "wss://custom-gateway.example.test",
  );
});

test("buildGatewayUrl supports a stored override", () => {
  assert.equal(
    buildGatewayUrl(
      {
        hostname: "silver-space-codex-4173.app.github.dev",
        port: "",
        protocol: "https:",
        search: "",
      },
      8765,
      "wss://stored-gateway.example.test",
    ),
    "wss://stored-gateway.example.test",
  );
});

test("buildGatewayUrlCandidates includes fallbacks without duplicates", () => {
  assert.deepEqual(
    buildGatewayUrlCandidates({
      hostname: "silver-space-codex-4173.app.github.dev",
      port: "",
      protocol: "https:",
      search: "",
    }),
    [
      "wss://silver-space-codex-8765.app.github.dev",
      "wss://silver-space-codex-4173.app.github.dev",
    ],
  );
});

test("buildAttachmentPrompt includes text file contents and names unsupported files", () => {
  const attachments = [
    {
      content: "# Notes\nShip it",
      kind: "text",
      name: "notes.md",
    },
    {
      kind: "unsupported",
      name: "diagram.png",
      reason: "暂不支持读取 image/png",
    },
  ];

  assert.equal(
    buildAttachmentPrompt("总结附件", attachments),
    [
      "总结附件",
      "",
      "已附加文件：",
      "",
      "### notes.md",
      "```text",
      "# Notes\nShip it",
      "```",
      "",
      "### 未读取的附件",
      "- diagram.png：暂不支持读取 image/png",
    ].join("\n"),
  );
});

test("renderMarkdown escapes html and renders fenced code blocks", () => {
  const html = renderMarkdown("Hi <x>\n\n```diff\n+ added\n```");

  assert.match(html, /agent-message-content/);
  assert.match(html, /Hi &lt;x&gt;/);
  assert.match(html, /language-diff/);
  assert.match(html, /\+ added/);
});

test("createProjectRecord trims input and keeps optional path only when present", () => {
  assert.deepEqual(
    createProjectRecord(
      {
        name: "  My Project  ",
        path: "  /tmp/my-project  ",
      },
      () => "project-1",
      () => 42,
    ),
    {
      id: "project-1",
      name: "My Project",
      path: "/tmp/my-project",
      updatedAt: 42,
    },
  );

  assert.deepEqual(
    createProjectRecord({ name: "   " }, () => "project-2", () => 43),
    {
      id: "project-2",
      name: "未命名项目",
      updatedAt: 43,
    },
  );
});

test("createProjectRecordFromPath uses the selected directory basename", () => {
  assert.deepEqual(
    createProjectRecordFromPath(
      "/Users/me/code/lumak",
      () => "project-dir",
      () => 99,
    ),
    {
      id: "project-dir",
      name: "lumak",
      path: "/Users/me/code/lumak",
      updatedAt: 99,
    },
  );
});
