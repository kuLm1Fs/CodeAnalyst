<p align="center">
  <img src="web/assets/lumak-logo.png" alt="LumaK logo" width="72" />
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh.md">中文</a>
</p>

# LumaK

LumaK is a local-first coding agent runtime for understanding and safely editing codebases. It runs an LLM-driven tool loop inside a restricted workspace, exposes the same runtime through CLI, terminal TUI, and Web UI entry points, and records trace events so agent runs can be inspected and debugged.

The project is designed around a small, auditable core: workspace-scoped tools, explicit tool schemas, session memory, trace hooks, provider adapters, and a WebSocket gateway that lets different UIs share the same runtime behavior.

## Features

- **Local-first runtime**: run against a local workspace with path escape protection and ignored-directory filtering.
- **Tool-calling agent loop**: supports multi-step model requests, tool results, context truncation, deduplication, termination signals, and `max_steps` limits.
- **Safe filesystem tools**: read, write, search, glob, and exact-match `safe_edit` with unified diff output.
- **Code navigation tools**: Python file outlines, workspace code maps, and exact symbol lookup.
- **Session memory**: JSONL-backed conversation history per session.
- **Trace events**: records model requests, tool calls, timing, success/failure, and final session output.
- **Multiple providers**: MiniMax, Anthropic, OpenAI, DeepSeek, and custom OpenAI-compatible endpoints.
- **Multiple interfaces**: Python CLI, TypeScript terminal TUI, and Web UI via a shared WebSocket gateway.
- **Local skills**: load `.skills/` instructions and inject matching skills into the system prompt.

## Installation

LumaK uses Python 3.12+ and `uv`.

```shell
uv sync
cp .env.example .env
```

Edit `.env` and configure one provider key, for example:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
ANTHROPIC_MODEL_ID=claude-sonnet-4-5
```

For global CLI usage:

```shell
uv tool install --editable .
lumak --help
```

## Usage

Run a single prompt against the current directory:

```shell
uv run lumak "Where is the runtime loop?"
```

Start the interactive CLI:

```shell
uv run lumak
```

Start the Web UI and gateway:

```shell
cd web && npm install && npm run build
cd ..
uv run lumak web --workspace /path/to/your/repo
```

Then open `http://127.0.0.1:4173`.

Start the terminal TUI:

```shell
cd tui && npm install && npm run build
cd ..
uv run lumak tui --workspace /path/to/your/repo
```

Run only the WebSocket gateway:

```shell
uv run lumak gateway --workspace /path/to/your/repo
```

## Configuration

Provider configuration lives in `.env.example`. Set `LLM_PROVIDER` to one of:

- `minimax`
- `anthropic`
- `openai`
- `deepseek`

Custom OpenAI-compatible endpoints can be configured through the matching provider variables and base URL settings.

The Web UI can also send per-request provider configuration through the gateway payload.

## Architecture

```text
CLI / TUI / Web UI
        |
        v
WebSocket Gateway
  chat / project.switch / conversation.* / memory.get / trace.get
        |
        v
Agent Runtime
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

Core modules:

- `agent/runtime/loop.py`: asynchronous and synchronous agent loop.
- `agent/runtime/messages.py`: message serialization, context truncation, and step budget warnings.
- `agent/tools/registry.py`: tool schemas, handlers, timeout policy, retries, and metadata.
- `agent/tools/filesystems.py`: workspace-scoped filesystem tools.
- `gateway/app.py`: WebSocket protocol server and message dispatch.
- `gateway/chat.py`: gateway chat runner and response fallback behavior.
- `gateway/state.py`: workspace, memory, trace, and project state.
- `web/`: browser UI built with TypeScript and Vite.
- `tui/`: terminal UI built with TypeScript.
- `shared/`: shared gateway contract helpers and types.

## Built-in Tools

| Tool | Description |
| --- | --- |
| `glob` | Find files matching a glob pattern inside the workspace. |
| `read_file` | Read UTF-8 text files with optional line paging. |
| `search_text` | Search text with ripgrep and return file, line number, and matching content. |
| `write_file` | Write UTF-8 text files inside the workspace. |
| `safe_edit` | Replace exact text once and return a unified diff; supports preview mode. |
| `file_outline` | Return imports, classes, functions, and methods for a Python file. |
| `code_map` | Build a workspace-level map of Python definitions. |
| `symbol_lookup` | Find Python class, function, or method definitions by exact name. |
| `delegate` | Run a restricted sub-agent for exploratory, review, or editing tasks. |

## Gateway Protocol

The Web UI and TUI communicate with the runtime through the gateway. Supported message families include:

| Message | Purpose |
| --- | --- |
| `chat` | Run an agent turn. |
| `project.list` / `project.get` | Inspect the active workspace. |
| `project.switch` | Switch the workspace for a session. |
| `conversation.list` / `conversation.get` | Read persisted session history. |
| `memory.get` | Inspect memory for a session. |
| `trace.get` | Read JSONL trace events for a session. |
| `ping` | Health check. |

## Local Skills

LumaK can load local skills from `.skills/`. A skill directory contains metadata and prompt instructions:

```text
.skills/<skill-name>/
├─ _meta.json
└─ SKILL.md
```

When a user message matches a skill name or trigger, the skill instructions are added to the system prompt for that run.

## Development

Run the Python test suite:

```shell
uv run pytest
```

Run Web UI tests:

```shell
cd web
npm test
```

Run TUI tests:

```shell
cd tui
npm test
```

Manual eval notes live in `evals/`.

## Contributing

Issues and pull requests are welcome. For changes that affect runtime behavior, please include focused tests around the tool loop, gateway protocol, filesystem guard, or UI contract that changed.

Before opening a pull request, run the relevant checks:

```shell
uv run pytest
cd web && npm test
cd ../tui && npm test
```

## License

MIT
