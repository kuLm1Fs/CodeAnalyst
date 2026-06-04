import assert from "node:assert/strict";
import test from "node:test";

import { TerminalUi, renderInputFrame, renderMessageBox, renderToolInline } from "../dist/terminal-ui.js";

test("input frame uses divider line and chevron prompt", () => {
  const lines = renderInputFrame("hello", "Idle", 50);

  assert.equal(lines.length, 2);
  assert.equal(stripAnsi(lines[0]), "─".repeat(50));
  assert.equal(stripAnsi(lines[1]), "❯ hello");
});

test("terminal cursor anchors on the input text row after rendered text", () => {
  const runtime = {
    subscribe() {
      return () => {};
    },
    dispose() {},
    sendMessage() {
      return Promise.resolve();
    },
  };
  const ui = new TerminalUi(runtime, {
    projectName: "LumaK",
    model: "test-model",
    workspace: "/tmp/lumak",
  });
  ui.input = "hello";

  const originalRows = process.stdout.rows;
  const originalColumns = process.stdout.columns;
  const originalWrite = process.stdout.write;
  let output = "";

  try {
    process.stdout.rows = 20;
    process.stdout.columns = 60;
    process.stdout.write = (chunk) => {
      output += String(chunk);
      return true;
    };

    ui.render();
  } finally {
    process.stdout.rows = originalRows;
    process.stdout.columns = originalColumns;
    process.stdout.write = originalWrite;
  }

  assert.match(output, /\x1b\[20;8H$/);
});

test("message renders role label and indented content", () => {
  const lines = renderMessageBox(
    {
      kind: "message",
      role: "lumaK",
      content: "Aloha! 👋 How can I help you today?",
    },
    48,
  );

  assert.equal(lines.length, 2);
  assert.match(lines[0], /lumaK/);
  assert.match(lines[1], /Aloha!/);
});

test("message renders markdown bold without visible delimiters", () => {
  const lines = renderMessageBox(
    {
      kind: "message",
      role: "lumaK",
      content: "我是来帮你干活的。**说正事，别客套。**",
    },
    60,
  );

  assert.equal(stripAnsi(lines[1]), "  我是来帮你干活的。说正事，别客套。");
  assert.match(lines[1], /\x1b\[1m说正事，别客套。\x1b\[22m/);
  assert.doesNotMatch(lines[1], /\*\*/);
});

test("tool inline shows status dot and tool name", () => {
  const lines = renderToolInline(
    {
      id: "tool-1",
      name: "Bash",
      args: { command: "echo done" },
      status: "success",
      resultPreview: "done",
    },
    48,
  );

  assert.equal(lines.length, 1);
  assert.match(lines[0], /Bash/);
  assert.match(lines[0], /\x1b\[90m●\x1b\[0m/);
});

test("tool inline shows green dot when running", () => {
  const lines = renderToolInline(
    {
      id: "tool-1",
      name: "read_file",
      args: { path: "src/main.ts" },
      status: "running",
    },
    48,
  );

  assert.equal(lines.length, 1);
  assert.match(lines[0], /read_file/);
  assert.match(lines[0], /\x1b\[32m●\x1b\[0m/);
});

test("system messages stay visually muted", () => {
  const lines = renderMessageBox(
    {
      kind: "message",
      role: "system",
      content: "Screen cleared.",
    },
    36,
  );

  assert.match(lines[0], /\x1b\[90m/);
  assert.match(lines[0], /system/);
});

function stripAnsi(text) {
  return text.replace(/\x1b\[[0-9;]*m/g, "");
}
