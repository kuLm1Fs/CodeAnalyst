<p align="center">
  <img src="web/assets/lumak-logo.png" alt="LumaK logo" width="72" />
</p>

<p align="center">
  <strong>中文</strong> · <a href="README.md">English</a>
</p>

# LumaK

LumaK 是一个本地优先的代码 Agent 运行时，用于理解代码库并在受控范围内安全修改文件。它在受限 workspace 内运行 LLM tool-calling 循环，通过 CLI、终端 TUI 和 Web UI 暴露同一套运行时能力，并记录 trace 事件，方便检查和调试 agent 执行过程。

这个项目围绕一个小而可审计的核心构建：workspace 范围内的工具、显式工具 schema、会话记忆、trace hook、provider 适配器，以及让不同 UI 共享同一运行时行为的 WebSocket gateway。

## 功能特性

- **本地优先运行时**：针对本地 workspace 运行，包含路径逃逸防护和忽略目录过滤。
- **Tool-calling agent 循环**：支持多轮模型请求、工具结果回填、上下文截断、工具去重、终止信号和 `max_steps` 限制。
- **安全文件系统工具**：读取、写入、搜索、glob，以及带 unified diff 的精确匹配 `safe_edit`。
- **代码导航工具**：Python 文件 outline、workspace 代码地图、精确符号查找。
- **会话记忆**：基于 JSONL 的 session 历史记录。
- **Trace 事件**：记录模型请求、工具调用、耗时、成功/失败和最终输出。
- **多 provider 支持**：MiniMax、Anthropic、OpenAI、DeepSeek，以及自定义 OpenAI-compatible 端点。
- **多入口界面**：Python CLI、TypeScript 终端 TUI、通过 WebSocket gateway 连接的 Web UI。
- **本地技能系统**：加载 `.skills/` 指令，并将匹配到的技能注入 system prompt。

## 安装

LumaK 需要 Python 3.12+ 和 `uv`。

```shell
uv sync
cp .env.example .env
```

编辑 `.env`，配置一个 provider key，例如：

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
ANTHROPIC_MODEL_ID=claude-sonnet-4-5
```

安装为全局 CLI：

```shell
uv tool install --editable .
lumak --help
```

## 使用

针对当前目录运行一次提问：

```shell
uv run lumak "runtime loop 在哪里？"
```

启动交互式 CLI：

```shell
uv run lumak
```

启动 Web UI 和 gateway：

```shell
cd web && npm install && npm run build
cd ..
uv run lumak web --workspace /path/to/your/repo
```

然后打开 `http://127.0.0.1:4173`。

启动终端 TUI：

```shell
cd tui && npm install && npm run build
cd ..
uv run lumak tui --workspace /path/to/your/repo
```

只启动 WebSocket gateway：

```shell
uv run lumak gateway --workspace /path/to/your/repo
```

## 配置

Provider 配置参考 `.env.example`。`LLM_PROVIDER` 可设置为：

- `minimax`
- `anthropic`
- `openai`
- `deepseek`

自定义 OpenAI-compatible 端点可通过对应 provider 变量和 base URL 配置。

Web UI 也可以通过 gateway payload 发送单次请求的 provider 配置。

## 架构

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

核心模块：

- `agent/runtime/loop.py`：同步和异步 agent 循环。
- `agent/runtime/messages.py`：消息序列化、上下文截断和 step budget 提示。
- `agent/tools/registry.py`：工具 schema、handler、超时策略、重试和元数据。
- `agent/tools/filesystems.py`：workspace 范围内的文件系统工具。
- `gateway/app.py`：WebSocket 协议服务和消息分发。
- `gateway/chat.py`：gateway chat runner 和响应兜底逻辑。
- `gateway/state.py`：workspace、memory、trace 和 project 状态。
- `web/`：基于 TypeScript 和 Vite 的浏览器 UI。
- `tui/`：基于 TypeScript 的终端 UI。
- `shared/`：共享 gateway contract helper 和类型。

## 内置工具

| 工具 | 说明 |
| --- | --- |
| `glob` | 按 glob pattern 查找 workspace 内文件。 |
| `read_file` | 分页读取 UTF-8 文本文件。 |
| `search_text` | 使用 ripgrep 搜索文本，返回文件、行号和匹配内容。 |
| `write_file` | 在 workspace 内写入 UTF-8 文本文件。 |
| `safe_edit` | 精确替换一次文本并返回 unified diff；支持 preview 模式。 |
| `file_outline` | 返回 Python 文件的 import、class、function 和 method。 |
| `code_map` | 构建 workspace 级 Python 定义地图。 |
| `symbol_lookup` | 按精确名称查找 Python class、function 或 method 定义。 |
| `delegate` | 运行受限子 agent，用于探索、审查或编辑任务。 |

## Gateway 协议

Web UI 和 TUI 通过 gateway 与 runtime 通信。支持的消息类型包括：

| 消息 | 用途 |
| --- | --- |
| `chat` | 运行一次 agent turn。 |
| `project.list` / `project.get` | 查看当前 workspace。 |
| `project.switch` | 切换某个 session 的 workspace。 |
| `conversation.list` / `conversation.get` | 读取持久化 session 历史。 |
| `memory.get` | 查看某个 session 的记忆。 |
| `trace.get` | 读取某个 session 的 JSONL trace 事件。 |
| `ping` | 健康检查。 |

## 本地技能

LumaK 可以从 `.skills/` 加载本地技能。一个技能目录包含元数据和 prompt 指令：

```text
.skills/<skill-name>/
├─ _meta.json
└─ SKILL.md
```

当用户消息匹配技能名称或触发词时，该技能指令会被加入本次运行的 system prompt。

## 开发

运行 Python 测试：

```shell
uv run pytest
```

运行 Web UI 测试：

```shell
cd web
npm test
```

运行 TUI 测试：

```shell
cd tui
npm test
```

手动评测记录在 `evals/` 中。

## 贡献

欢迎提交 issue 和 pull request。涉及 runtime 行为的修改，请为变更的 tool loop、gateway 协议、filesystem guard 或 UI contract 添加聚焦测试。

提交 pull request 前，建议运行相关检查：

```shell
uv run pytest
cd web && npm test
cd ../tui && npm test
```

## 许可证

MIT
