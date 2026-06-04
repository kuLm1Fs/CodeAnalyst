import assert from "node:assert/strict";
import test from "node:test";

import { parseCliArgs } from "../dist/app-utils.js";
import { GatewayAgentRuntime, buildGatewayEnvironment } from "../dist/gateway-runtime.js";

test("gateway runtime maps websocket messages onto TUI events", () => {
  const args = parseCliArgs(["--runtime", "gateway", "--session", "s1", "--workspace", "/tmp"]);
  const runtime = new GatewayAgentRuntime(args, "/tmp/lumak");
  const events = [];
  runtime.subscribe((event) => events.push(event));

  runtime.handleGatewayMessage({ type: "chat.started", session_id: "s1" });
  runtime.handleGatewayMessage({
    type: "agent.event",
    event: "tool.before",
    session_id: "s1",
    payload: {
      tool_use_id: "tool-1",
      tool_name: "read_file",
      tool_input: { path: "README.md" },
    },
  });
  runtime.handleGatewayMessage({
    type: "agent.event",
    event: "tool.after",
    session_id: "s1",
    payload: {
      tool_use_id: "tool-1",
      tool_name: "read_file",
      success: true,
      output: "# LumaK",
    },
  });
  runtime.handleGatewayMessage({ type: "chat.response", session_id: "s1", answer: "done" });

  assert.deepEqual(
    events.map((event) => event.type),
    ["status_update", "tool_call_start", "status_update", "tool_call_end", "status_update", "thinking_end", "assistant_message", "status_update"],
  );
  assert.equal(events.find((event) => event.type === "tool_call_start")?.name, "read_file");
  assert.equal(events.find((event) => event.type === "tool_call_end")?.resultPreview, "# LumaK");
  assert.equal(events.find((event) => event.type === "assistant_message")?.content, "done");

  runtime.dispose();
});

test("gateway runtime loads provider config from workspace dotenv", () => {
  const env = buildGatewayEnvironment(
    "/tmp/project",
    {
      MINIMAX_API_KEY: "shell-key",
    },
    (path) => {
      assert.equal(path, "/tmp/project/.env");
      return [
        "MINIMAX_API_KEY=dotenv-key",
        "MINIMAX_BASE_URL=https://api.minimax.example/v1",
        "MINIMAX_MODEL_ID='minimax-text-01'",
      ].join("\n");
    },
  );

  assert.equal(env.MINIMAX_API_KEY, "shell-key");
  assert.equal(env.MINIMAX_BASE_URL, "https://api.minimax.example/v1");
  assert.equal(env.MINIMAX_MODEL_ID, "minimax-text-01");
});
