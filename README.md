<p align="center">
  <img src="web/assets/lumak-logo.png" alt="LumaK logo" width="72" />
</p>

<p align="center">
  <strong>Portfolio README</strong> · <a href="README.zh.md">中文旧版</a>
</p>

# LumaK

**Local-first Coding Agent Runtime for codebase understanding and safe small edits.**

LumaK is a local coding agent runtime, not a thin chat API wrapper. It runs an LLM-driven tool loop inside a restricted workspace, exposes the same runtime through CLI / TypeScript TUI / Web UI, and records the execution as trace events so a failed agent run can be debugged after the fact.

**What to look at in 30 seconds**

- Runtime loop: `agent/runtime/loop.py`
- Agent wrapper: `agent/runtime/agent/agent.py`
- Tool registry and workspace guard: `agent/tools/registry.py`, `agent/tools/filesystems.py`
- Trace hooks and live events: `agent/trace/trace.py`, `gateway/events.py`
- WebSocket gateway APIs: `gateway/app.py`, `gateway/state.py`
- Web / TUI entry points: `web/src/app.ts`, `tui/src/gateway-runtime.ts`
- Skills and eval notes: `agent/skills/`, `.skills/`, `evals/`

## Why This Is Not Just an API Wrapper

普通 LLM API 套壳通常只有「输入 prompt -> 返回文本」。LumaK 的重点是 Agent 工程里更难验证的部分：

- **Runtime control**: multi-step loop, tool-use parsing, tool-result feedback, `max_steps`, dedup, context truncation, and fallback messages.
- **Tool execution**: model-chosen tools for file reading, search, structured code outline, safe edit preview, and workspace-scoped writes.
- **Safety boundary**: path escape prevention, ignored directory filtering, UTF-8 checks, exact-match edit, and rollback hooks.
- **Observability**: JSONL trace for model requests, tool arguments, latency, success/failure, and final output.
- **Multi-entry UI**: CLI for fast use, TUI for terminal demo, Web UI for visualizing live events, memory, project state, and trace.
- **Extensibility**: local `.skills/` prompt injection and manual eval tasks for behavior regression.

## Quick Start

```shell
uv sync
cp .env.example .env
# edit .env with one provider key, for example ANTHROPIC_API_KEY or OPENAI_API_KEY

# CLI, default workspace is current directory
uv run lumak "Where is the runtime loop?"

# interactive CLI
uv run lumak

# Web UI + gateway, then open http://127.0.0.1:4173
cd web && npm install && npm run build
cd ..
uv run lumak web --workspace /path/to/your/repo

# TypeScript terminal TUI
cd tui && npm install && npm run build
cd ..
uv run lumak tui --workspace /path/to/your/repo
```

Provider config lives in `.env.example`. Supported provider families include MiniMax, Anthropic, OpenAI, DeepSeek, and OpenAI-compatible endpoints.

## Core Architecture

```text
CLI / TUI / Web UI
        |
        v
WebSocket Gateway
  chat / project.switch / conversation.* / memory.get / trace.get
        |
        v
Agent(Runtime)
  session history -> skill selection -> model request -> tool_use
        |
        v
Tool Registry
  read_file / write_file / glob / search_text / safe_edit
  file_outline / code_map / symbol_lookup / delegate
        |
        v
Workspace Guard + Trace + Memory + Hooks
```

### Runtime Loop

`agent/runtime/loop.py` implements the agent loop:

1. load session history from `MemoryStore`
2. select matching local skills from `.skills/`
3. send messages and tool schemas to the configured model provider
4. parse `tool_use` blocks
5. execute tools inside the workspace guard
6. append `tool_result` blocks for the next model turn
7. emit hook events and persist trace
8. stop on final answer, termination, repeated dedup, or `max_steps`

### Gateway And UI

`gateway/app.py` turns the runtime into a WebSocket protocol. The Web UI and TUI do not own the agent logic; they subscribe to events and render state.

Supported message families include:

| Message | Purpose |
| --- | --- |
| `chat` | Run an agent turn |
| `project.list` / `project.get` / `project.switch` | Inspect or switch workspace |
| `conversation.list` / `conversation.get` | Read session history |
| `memory.get` | Inspect memory for one session |
| `trace.get` | Read JSONL trace events |
| `ping` | Health check |

### Tools

| Tool | What it proves |
| --- | --- |
| `glob` | File discovery under workspace constraints |
| `read_file` | Bounded UTF-8 file reading |
| `search_text` | Keyword search with path and line numbers |
| `write_file` | Workspace-scoped file writing |
| `safe_edit` | Exact-match replacement with unified diff preview |
| `file_outline` | Structured Python file outline from definitions/imports |
| `code_map` | Workspace-level Python definition map |
| `symbol_lookup` | Exact symbol lookup by class/function/method name |
| `delegate` | Sub-agent task delegation with restricted tool sets |

## Interviewer Reading Path

If you only have 10 minutes, read in this order:

1. `lumak/cli.py`: confirms the real commands: `lumak`, `lumak gateway`, `lumak web`, `lumak tui`.
2. `agent/runtime/loop.py`: confirms the multi-step agent loop and trace hook points.
3. `agent/tools/filesystems.py`: confirms workspace guard, ignored directories, and `safe_edit`.
4. `gateway/app.py` + `gateway/state.py`: confirms WebSocket API, project switching, history, memory, and trace endpoints.
5. `tui/src/gateway-runtime.ts` + `web/src/app.ts`: confirms TUI/Web consume the same gateway instead of duplicating runtime logic.
6. `evals/session-history-pollution.md`: shows a real debugging case and the fixes made from trace evidence.

## Demo Flow

Recommended short demo for interviews:

1. Start Web UI:

   ```shell
   uv run lumak web --workspace /Users/poikoi/code/lumaK
   ```

2. Ask: `agent runtime 的主循环在哪里？`
   Expected: LumaK identifies `agent/runtime/loop.py` and explains the tool loop.

3. Ask: `文件工具有哪些安全边界？`
   Expected: mentions workspace restriction, ignored directories, UTF-8 text, path escape rejection, and safe edit behavior.

4. Ask for a safe edit preview on a temporary file:
   Expected: `safe_edit(..., preview=true)` returns a diff without writing.

5. Open the details panel in Web UI or call `trace.get`:
   Expected: see `model.request`, `tool.before`, `tool.after`, and `session.end` events.

6. Run the TUI against the same workspace:

   ```shell
   uv run lumak tui --workspace /Users/poikoi/code/lumaK
   ```

   Expected: terminal UI shows the same runtime events through the gateway path.

## Tests And Evals

```shell
uv run pytest
cd web && npm test
cd ../tui && npm test
```

Manual eval tasks live in `evals/tasks.md`. Debugging writeups live in `evals/`, especially `session-history-pollution.md`, which records how trace evidence was used to fix memory pollution, `glob("**/*")` hangs, and empty response fallback.

## Current Scope

This project is intentionally scoped as an interview portfolio for Agent engineering:

- proves runtime control, tool calling, workspace safety, traceability, and UI/runtime separation
- does not try to become a full production IDE agent
- prioritizes demo reliability and source-code evidence over broad feature count

## License

MIT
