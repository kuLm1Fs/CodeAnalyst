from __future__ import annotations

import json
from pathlib import Path
from typing import Any


READONLY_TOOLS = {"read_file", "glob", "search_text", "file_outline", "code_map", "symbol_lookup"}


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
    max_steps: int = 6,
    context: str = "",
    workspace: str | Path | None = None,
) -> str:
    from agent.runtime.loop import agent_loop
    from agent.tools.registry import registry

    workspace = Path(workspace) if workspace else Path.cwd()

    allowed_tools = list(tools or READONLY_TOOLS)
    tool_schemas = registry.get_schemas(allowed_tools)
    if not tool_schemas:
        return json.dumps({
            "status": "error",
            "error": f"No valid tools found. Requested: {allowed_tools}",
        })

    messages: list[dict[str, Any]] = []
    user_content = task
    if context:
        user_content = f"{task}\n\nAdditional context:\n{context}"
    messages.append({"role": "user", "content": user_content})

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
        )

        answer = _response_to_text(response)
        stop_reason = getattr(response, "stop_reason", "unknown")

        return json.dumps({
            "status": "completed",
            "answer": answer,
            "stop_reason": stop_reason,
            "steps_used": max_steps,
        }, ensure_ascii=False)

    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": str(exc),
        }, ensure_ascii=False)
