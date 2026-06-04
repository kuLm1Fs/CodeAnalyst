import assert from "node:assert/strict";
import test from "node:test";

import {
  displayRole,
  formatAgentEvent,
  formatArgsSummary,
  padRight,
  parseCliArgs,
  parseLocalGatewayUrl,
  truncateText,
  wrapText,
} from "../dist/app-utils.js";

test("formatAgentEvent shows skills, model, tool progress, and session end", () => {
  assert.equal(formatAgentEvent("skills.selected", { skill_names: ["docs", "review"] }), "Skills: docs, review");
  assert.equal(formatAgentEvent("skills.selected", { skill_names: [] }), "Skills: none");
  assert.equal(formatAgentEvent("model.request", { model: "gpt-5.1" }), "Model request: gpt-5.1");
  assert.equal(formatAgentEvent("tool.before", { tool_name: "read_file" }), "Tool starting: read_file");
  assert.equal(formatAgentEvent("tool.after", { tool_name: "safe_edit", success: false }), "Tool failed: safe_edit");
  assert.equal(formatAgentEvent("session.end", {}), "Session complete");
  assert.equal(formatAgentEvent("unknown", {}), null);
});

test("wrapText preserves blank lines and wraps long content", () => {
  assert.deepEqual(wrapText("short", 10), ["short"]);
  assert.deepEqual(wrapText("alpha beta gamma", 8), ["alpha", "beta", "gamma"]);
  assert.deepEqual(wrapText("", 8), [""]);
});

test("parseCliArgs accepts gateway, session, workspace, and token options", () => {
  const args = parseCliArgs([
    "--gateway",
    "ws://localhost:9000",
    "--session",
    "session-1",
    "--workspace",
    "/tmp/demo",
    "--max-tokens",
    "2048",
    "--model",
    "gpt-demo",
    "--runtime",
    "mock",
  ]);

  assert.equal(args.gatewayUrl, "ws://localhost:9000");
  assert.equal(args.sessionId, "session-1");
  assert.equal(args.workspace, "/tmp/demo");
  assert.equal(args.maxTokens, 2048);
  assert.equal(args.model, "gpt-demo");
  assert.equal(args.runtime, "mock");
});

test("parseCliArgs defaults to the real gateway runtime", () => {
  const args = parseCliArgs([]);

  assert.equal(args.runtime, "gateway");
});

test("parseLocalGatewayUrl accepts only local websocket gateways", () => {
  assert.deepEqual(parseLocalGatewayUrl("ws://127.0.0.1:8765"), { host: "127.0.0.1", port: "8765" });
  assert.deepEqual(parseLocalGatewayUrl("ws://localhost"), { host: "localhost", port: "8765" });
  assert.equal(parseLocalGatewayUrl("ws://example.com:8765"), null);
  assert.equal(parseLocalGatewayUrl("not a url"), null);
});

test("displayRole presents assistant messages as lumak", () => {
  assert.equal(displayRole("assistant"), "lumak");
  assert.equal(displayRole("you"), "you");
  assert.equal(displayRole("event"), "event");
});

test("compact formatting helpers keep text within terminal bounds", () => {
  assert.equal(truncateText("abcdefgh", 6), "abc...");
  assert.equal(padRight("abc", 5), "abc  ");
  assert.equal(formatArgsSummary({ query: "hello", limit: 3 }, 80), 'query="hello" limit=3');
  assert.equal(formatArgsSummary({ include: ["src", "tests"] }, 80), 'include=["src","tests"]');
});
