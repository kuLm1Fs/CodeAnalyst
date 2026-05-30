from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


READONLY_TOOLS = {"read_file", "glob", "search_text", "file_outline", "code_map", "symbol_lookup"}

VALID_ROLES = {"explorer", "editor", "reviewer"}


def _response_to_text(response: Any) -> str:
    if isinstance(response, list):
        return ""
    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    return "\n".join(texts).strip()


def run_delegate(
    task: str,
    tools: list[str] | None = None,
    max_steps: int = 15,
    context: str = "",
    role: str = "explorer",
    workspace: str | Path | None = None,
) -> str:
    from agent.runtime.loop import agent_loop
    from agent.tools.registry import registry

    workspace = Path(workspace) if workspace else Path.cwd()

    if role not in VALID_ROLES:
        role = "explorer"

    allowed_tools = list(tools or READONLY_TOOLS)
    tool_schemas = registry.get_schemas(allowed_tools)
    if not tool_schemas:
        return json.dumps({
            "status": "error",
            "task": task,
            "role": role,
            "error": f"No valid tools found. Requested: {allowed_tools}",
        })

    messages: list[dict[str, Any]] = []
    user_content = task
    if context:
        user_content = f"{task}\n\nAdditional context:\n{context}"
    messages.append({"role": "user", "content": user_content})

    start_time = time.perf_counter()
    try:
        response = agent_loop(
            messages=messages,
            max_tokens=2048,
            workspace=workspace,
            max_steps=max_steps,
            hooks=None,
            memory_store=None,
            skills_root=None,
            trace_enabled=False,
            role=role,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        answer = _response_to_text(response)
        stop_reason = getattr(response, "stop_reason", "unknown")

        return json.dumps({
            "status": "completed",
            "task": task,
            "role": role,
            "answer": answer,
            "stop_reason": stop_reason,
            "max_steps": max_steps,
            "elapsed_ms": round(elapsed_ms),
        }, ensure_ascii=False)

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return json.dumps({
            "status": "error",
            "task": task,
            "role": role,
            "error": str(exc),
            "elapsed_ms": round(elapsed_ms),
        }, ensure_ascii=False)
