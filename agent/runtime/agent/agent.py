from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agent.runtime.loop import agent_loop, async_agent_loop
from agent.trace.trace import make_session_id
from agent.runtime.hooks import Hook
from agent.memory.store import MemoryStore

ROLE_PROMPT_FILES = {
    "main": "system.md",
    "explorer": "subagent-explorer.md",
    "editor": "subagent-editor.md",
    "reviewer": "subagent-reviewer.md",
}


@dataclass(frozen=True)
class AgentConfig:
    workspace: Path
    max_steps: int = 30
    max_tokens: int = 4096
    session_id: str | None = None
    llm_client: object | None = None
    hooks: list[Hook] | None = None
    memory_store: MemoryStore | None = None
    skills_root: Path | str | None = None
    trace_enabled: bool = False
    trace_payload_limit: int = 2000
    role: str = "main"
    prompt_override: str | None = None


class Agent:
    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig(workspace=Path.cwd())
        self.session_id = self.config.session_id or make_session_id()

    def run(self, messages: list[dict]) -> object:

        return agent_loop(
            messages=messages,
            max_tokens=self.config.max_tokens,
            max_steps=self.config.max_steps,
            workspace=self.config.workspace,
            session_id=self.session_id,
            llm_client=self.config.llm_client,
            hooks=self.config.hooks,
            memory_store=self.config.memory_store,
            skills_root=self.config.skills_root,
            trace_enabled=self.config.trace_enabled,
            trace_payload_limit=self.config.trace_payload_limit,
            role=self.config.role,
            prompt_override=self.config.prompt_override,
        )

    async def async_run(self, messages: list[dict]) -> object:

        return await async_agent_loop(
            messages=messages,
            max_tokens=self.config.max_tokens,
            max_steps=self.config.max_steps,
            workspace=self.config.workspace,
            session_id=self.session_id,
            llm_client=self.config.llm_client,
            hooks=self.config.hooks,
            memory_store=self.config.memory_store,
            skills_root=self.config.skills_root,
            trace_enabled=self.config.trace_enabled,
            trace_payload_limit=self.config.trace_payload_limit,
            role=self.config.role,
            prompt_override=self.config.prompt_override,
        )
